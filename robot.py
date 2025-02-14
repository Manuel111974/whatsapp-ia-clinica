import os
import redis
import requests
import json
from bs4 import BeautifulSoup
from rapidfuzz import process
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# 🔧 Configuración de Flask
app = Flask(__name__)

# 🔧 Configuración de Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# 🔧 Configuración de Koibox API
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"
HEADERS = {
    "X-Koibox-Key": KOIBOX_API_KEY,
    "Content-Type": "application/json"
}

# 📌 ID de Gabriel en Koibox (⚠️ Ajustar con el ID correcto)
GABRIEL_USER_ID = 1  

# 📌 Normalizar números de teléfono
def normalizar_telefono(telefono):
    telefono = telefono.strip().replace(" ", "").replace("-", "")
    if not telefono.startswith("+34"):  
        telefono = "+34" + telefono
    return telefono

# 🔍 Buscar cliente en Koibox
def buscar_cliente(telefono):
    telefono = normalizar_telefono(telefono)
    url = f"{KOIBOX_URL}/clientes/"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        clientes_data = response.json()
        for cliente in clientes_data.get("results", []):
            if normalizar_telefono(cliente.get("movil")) == telefono:
                return cliente.get("id")
    return None

# 🆕 Crear cliente en Koibox
def crear_cliente(nombre, telefono):
    telefono = normalizar_telefono(telefono)
    datos_cliente = {
        "nombre": nombre,
        "movil": telefono,
        "notas": "Cliente registrado por Gabriel IA.",
        "is_anonymous": False
    }
    response = requests.post(f"{KOIBOX_URL}/clientes/", headers=HEADERS, json=datos_cliente)

    if response.status_code == 201:
        return response.json().get("id")
    return None

# 📄 Obtener servicios de Koibox
def obtener_servicios():
    url = f"{KOIBOX_URL}/servicios/"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        servicios_data = response.json()
        return {s["nombre"]: s["id"] for s in servicios_data.get("results", [])}
    return {}

# 🔍 Buscar el servicio más parecido
def encontrar_servicio_mas_parecido(servicio_solicitado):
    servicios = obtener_servicios()
    if not servicios:
        return None, "No hay servicios disponibles."

    mejor_match, score, _ = process.extractOne(servicio_solicitado, servicios.keys())

    if score > 75:
        return servicios[mejor_match], f"Se ha seleccionado el servicio más parecido: {mejor_match}"
    
    return None, "No encontré un servicio similar."

# 📆 Crear cita en Koibox
def crear_cita(cliente_id, nombre, telefono, fecha, hora, servicio_solicitado):
    servicio_id, mensaje = encontrar_servicio_mas_parecido(servicio_solicitado)

    if not servicio_id:
        return False, mensaje

    datos_cita = {
        "fecha": fecha,
        "hora_inicio": hora,
        "hora_fin": calcular_hora_fin(hora, 1),
        "titulo": servicio_solicitado,
        "notas": "Cita agendada por Gabriel IA",
        "user": {"value": GABRIEL_USER_ID, "text": "Gabriel Asistente IA"},
        "cliente": {"value": cliente_id, "text": nombre, "movil": telefono},
        "servicios": [{"value": servicio_id}],
        "estado": 1
    }
    
    response = requests.post(f"{KOIBOX_URL}/agenda/cita/", headers=HEADERS, json=datos_cita)
    
    if response.status_code == 201:
        return True, "✅ ¡Tu cita ha sido creada con éxito!"
    return False, f"⚠️ No se pudo agendar la cita: {response.text}"

# ⏰ Calcular hora de finalización
def calcular_hora_fin(hora_inicio, duracion_horas):
    h, m = map(int, hora_inicio.split(":"))
    h += duracion_horas
    return f"{h:02d}:{m:02d}"

# 📌 Actualizar notas en Koibox
def actualizar_notas_paciente(cliente_id, nueva_nota):
    response = requests.get(f"{KOIBOX_URL}/clientes/{cliente_id}/", headers=HEADERS)
    
    if response.status_code == 200:
        cliente_data = response.json()
        notas_actuales = cliente_data.get("notas", "")
        
        notas_actualizadas = f"{notas_actuales}\n{nueva_nota}"
        cliente_data["notas"] = notas_actualizadas
        
        update_response = requests.put(f"{KOIBOX_URL}/clientes/{cliente_id}/", headers=HEADERS, data=json.dumps(cliente_data))
        
        return update_response.status_code == 200
    return False

# 🌐 Obtener ofertas desde Facebook
def obtener_ofertas_facebook():
    url = "https://www.facebook.com/Albane-ClinicSonrisas-Hollywood-100070445980447/"
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, "html.parser")
        publicaciones = soup.find_all("div", class_="du4w35lb")
        ofertas = [p.get_text() for p in publicaciones if "oferta" in p.get_text().lower()]
        return ofertas
    return []

# 📩 Webhook de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    resp = MessagingResponse()
    msg = resp.message()

    estado_usuario = redis_client.get(sender + "_estado")

    if incoming_msg in ["hola", "buenas", "qué tal", "hey"]:
        msg.body("¡Hola! 😊 Soy Gabriel, el asistente de Sonrisas Hollywood. ¿En qué puedo ayudarte?")
        return str(resp)

    if "oferta" in incoming_msg:
        ofertas = obtener_ofertas_facebook()
        msg.body("\n".join(ofertas) if ofertas else "No se encontraron ofertas actuales.")
        return str(resp)

    if "cita" in incoming_msg:
        redis_client.set(sender + "_estado", "esperando_nombre", ex=600)
        msg.body("¡Genial! Primero dime tu nombre completo 😊.")
        return str(resp)

    if estado_usuario == "esperando_nombre":
        redis_client.set(sender + "_nombre", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_telefono", ex=600)
        msg.body(f"Gracias, {incoming_msg}. Ahora dime tu número de teléfono 📞.")
        return str(resp)

    if estado_usuario == "esperando_telefono":
        redis_client.set(sender + "_telefono", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_fecha", ex=600)
        msg.body("¡Perfecto! ¿Qué día prefieres? 📅")
        return str(resp)

    if estado_usuario == "esperando_servicio":
        cliente_id = buscar_cliente(sender) or crear_cliente(sender, incoming_msg)
        actualizar_notas_paciente(cliente_id, incoming_msg)
        msg.body("✅ Información guardada en tu ficha. ¿Necesitas algo más?")
        return str(resp)

    msg.body("No entendí tu mensaje. ¿Podrías reformularlo? 😊")
    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
