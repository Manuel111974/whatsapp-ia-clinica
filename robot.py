import os
import redis
import requests
import json
from rapidfuzz import process
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# 🔹 Configuración de Flask
app = Flask(__name__)

# 🔹 Configuración de Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# 🔹 Configuración de Koibox API
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"

HEADERS = {
    "X-Koibox-Key": KOIBOX_API_KEY,
    "Content-Type": "application/json"
}

# 🔹 ID de Gabriel en Koibox (Actualizar con el correcto)
GABRIEL_USER_ID = 1

# 🔹 Información de la clínica
INFO_CLINICA = {
    "nombre": "Sonrisas Hollywood Valencia",
    "telefono": "618 44 93 32",
    "ubicacion": "https://g.co/kgs/U5uMgPg",
    "ofertas": "https://www.facebook.com/share/1BeQpVyja5/?mibextid=wwXIfr"
}

# 🔹 Normalizar teléfono
def normalizar_telefono(telefono):
    telefono = telefono.strip().replace(" ", "").replace("-", "")
    if not telefono.startswith("+34"):
        telefono = "+34" + telefono
    return telefono

# 🔹 Buscar cliente en Koibox
def buscar_cliente(telefono):
    telefono = normalizar_telefono(telefono)
    url = f"{KOIBOX_URL}/clientes/"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        clientes_data = response.json()
        if "results" in clientes_data:
            for cliente in clientes_data["results"]:
                if normalizar_telefono(cliente.get("movil")) == telefono:
                    return cliente
    return None

# 🔹 Crear cliente en Koibox
def crear_cliente(nombre, telefono, notas=""):
    telefono = normalizar_telefono(telefono)
    datos_cliente = {
        "nombre": nombre,
        "movil": telefono,
        "notas": notas,
        "is_active": True,
        "is_anonymous": False
    }
    response = requests.post(f"{KOIBOX_URL}/clientes/", headers=HEADERS, json=datos_cliente)

    if response.status_code == 201:
        return response.json()
    return None

# 🔹 Obtener lista de servicios desde Koibox
def obtener_servicios():
    url = f"{KOIBOX_URL}/servicios/"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        servicios_data = response.json()
        return {s["nombre"]: s["id"] for s in servicios_data.get("results", [])}
    return {}

# 🔹 Buscar el servicio más parecido
def encontrar_servicio_mas_parecido(servicio_solicitado):
    servicios = obtener_servicios()
    if not servicios:
        return None, "No hay servicios disponibles en este momento."

    mejor_match, score, _ = process.extractOne(servicio_solicitado, servicios.keys())

    if score > 75:
        return servicios[mejor_match], f"Se ha seleccionado el servicio más parecido: {mejor_match}"
    
    return None, "No encontré un servicio similar."

# 🔹 Crear cita en Koibox
def crear_cita(cliente_id, nombre, telefono, fecha, hora, servicio_solicitado, notas_cliente):
    servicio_id, mensaje = encontrar_servicio_mas_parecido(servicio_solicitado)

    if not servicio_id:
        return False, mensaje

    # Guardar la información en las notas del paciente
    notas_actualizadas = f"{notas_cliente}\nCita programada: {fecha} a las {hora} para {servicio_solicitado}"

    datos_cita = {
        "fecha": fecha,
        "hora_inicio": hora,
        "hora_fin": calcular_hora_fin(hora, 1),
        "titulo": servicio_solicitado,
        "notas": notas_actualizadas,
        "user": {"value": GABRIEL_USER_ID, "text": "Gabriel Asistente IA"},
        "cliente": {"value": cliente_id, "text": nombre, "movil": telefono},
        "servicios": [{"value": servicio_id}],
        "estado": 1
    }
    
    response = requests.post(f"{KOIBOX_URL}/agenda/cita/", headers=HEADERS, json=datos_cita)
    
    if response.status_code == 201:
        return True, "✅ ¡Tu cita ha sido creada con éxito!"
    return False, f"⚠️ No se pudo agendar la cita: {response.text}"

# 🔹 Calcular hora de finalización
def calcular_hora_fin(hora_inicio, duracion_horas):
    h, m = map(int, hora_inicio.split(":"))
    h += duracion_horas
    return f"{h:02d}:{m:02d}"

# 🔹 Webhook de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    resp = MessagingResponse()
    msg = resp.message()

    estado_usuario = redis_client.get(sender + "_estado")

    # 📌 Respuestas a saludos y mensajes casuales
    if incoming_msg in ["hola", "buenas", "qué tal", "hey"]:
        msg.body(f"¡Hola! 😊 Soy Gabriel, el asistente de {INFO_CLINICA['nombre']}. ¿En qué puedo ayudarte?")
        return str(resp)

    if incoming_msg in ["gracias", "ok", "vale"]:
        msg.body("¡De nada! Si necesitas algo más, aquí estoy. 😊")
        return str(resp)

    # 📌 Flujo de citas
    if "cita" in incoming_msg:
        redis_client.set(sender + "_estado", "esperando_nombre", ex=600)
        msg.body("¡Genial! Primero dime tu nombre completo 😊.")
        return str(resp)

    if estado_usuario == "esperando_nombre":
        redis_client.set(sender + "_nombre", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_fecha", ex=600)
        msg.body("Gracias. ¿Para qué fecha necesitas la cita? 📅 (Ejemplo: '2025-02-14')")
        return str(resp)

    if estado_usuario == "esperando_fecha":
        redis_client.set(sender + "_fecha", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_hora", ex=600)
        msg.body("Genial. ¿A qué hora prefieres la cita? ⏰ (Ejemplo: '11:00')")
        return str(resp)

    # 📌 Información de la clínica
    if "ubicación" in incoming_msg or "dónde están" in incoming_msg:
        msg.body(f"Nuestra clínica está en: {INFO_CLINICA['ubicacion']}")
        return str(resp)

    if "oferta" in incoming_msg or "promoción" in incoming_msg:
        msg.body(f"Aquí puedes ver nuestras ofertas: {INFO_CLINICA['ofertas']}")
        return str(resp)

    msg.body("No entendí tu mensaje. ¿Podrías reformularlo? 😊")
    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
