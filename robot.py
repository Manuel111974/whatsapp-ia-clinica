import os
import redis
import requests
from rapidfuzz import process  
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# 📌 Configuración de Flask
app = Flask(__name__)

# 📌 Configuración de Redis para manejo de sesiones
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# 📌 Configuración de Koibox API
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"

HEADERS = {
    "Authorization": f"Bearer {KOIBOX_API_KEY}",
    "Content-Type": "application/json"
}

# 📌 ID del empleado "Gabriel Asistente IA"
GABRIEL_USER_ID = 1  # ⚠️ Ajusta según corresponda

# 🔍 **Buscar cliente en Koibox**
def buscar_cliente(telefono):
    url = f"{KOIBOX_URL}/clientes/"
    response = requests.get(url, headers=HEADERS)
    
    if response.status_code == 200:
        clientes = response.json().get("results", [])
        for cliente in clientes:
            if cliente.get("movil") == telefono:
                print(f"✅ Cliente encontrado en Koibox: {cliente.get('id')} - {cliente.get('nombre')}")
                return cliente.get("id"), cliente.get("nombre")
    print(f"⚠️ Cliente no encontrado en Koibox con teléfono: {telefono}")
    return None, None  

# 🆕 **Crear cliente en Koibox si no existe**
def crear_cliente(nombre, telefono):
    datos_cliente = {
        "nombre": nombre,
        "movil": telefono,
        "is_anonymous": False
    }
    response = requests.post(f"{KOIBOX_URL}/clientes/", headers=HEADERS, json=datos_cliente)
    
    if response.status_code == 201:
        cliente_info = response.json()
        print(f"✅ Cliente creado en Koibox: {cliente_info.get('id')} - {cliente_info.get('nombre')}")
        return cliente_info.get("id"), cliente_info.get("nombre")
    else:
        print(f"❌ Error creando cliente en Koibox: {response.text}")
        return None, None

# 📄 **Obtener lista de servicios desde Koibox**
def obtener_servicios():
    url = f"{KOIBOX_URL}/servicios/"
    response = requests.get(url, headers=HEADERS)
    
    if response.status_code == 200:
        servicios = response.json().get("results", [])
        return {s["nombre"]: s["id"] for s in servicios}
    print(f"❌ Error al obtener servicios de Koibox: {response.text}")
    return {}

# 🔍 **Buscar el servicio más parecido**
def encontrar_servicio_mas_parecido(servicio_solicitado):
    servicios = obtener_servicios()
    if not servicios:
        return None, "No hay servicios disponibles."
    
    mejor_match, score, _ = process.extractOne(servicio_solicitado, servicios.keys())
    return (servicios[mejor_match], f"Se ha seleccionado: {mejor_match}") if score > 75 else (None, "No encontré un servicio similar.")

# 📆 **Crear cita en Koibox**
def crear_cita(cliente_id, cliente_nombre, fecha, hora, servicio_solicitado):
    servicio_id, mensaje = encontrar_servicio_mas_parecido(servicio_solicitado)
    
    if not servicio_id:
        return False, mensaje

    datos_cita = {
        "fecha": fecha,
        "hora_inicio": hora,
        "hora_fin": calcular_hora_fin(hora, 1),
        "titulo": servicio_solicitado,
        "notas": "Cita agendada por Gabriel (IA)",
        "user": {"value": GABRIEL_USER_ID, "text": "Gabriel Asistente IA"},  # Asignamos Gabriel IA
        "cliente": {"value": cliente_id, "text": cliente_nombre},  # Enviamos ID y nombre del cliente
        "servicios": [{"id": servicio_id, "value": servicio_id, "text": servicio_solicitado}],
        "estado": {"id": 1, "value": 1, "nombre": "Confirmado"}
    }

    print(f"📅 Creando cita con los siguientes datos: {datos_cita}")
    
    response = requests.post(f"{KOIBOX_URL}/agenda/", headers=HEADERS, json=datos_cita)
    
    if response.status_code in [200, 201]:
        print(f"✅ Cita creada correctamente en Koibox")
        return True, "✅ ¡Tu cita ha sido creada con éxito!"
    else:
        print(f"❌ Error al agendar la cita en Koibox: {response.text}")
        return False, f"⚠️ No se pudo agendar la cita: {response.text}"

# ⏰ **Calcular la hora de finalización**
def calcular_hora_fin(hora_inicio, duracion_horas):
    h, m = map(int, hora_inicio.split(":"))
    h += duracion_horas
    return f"{h:02d}:{m:02d}"

# 📩 **Webhook para recibir mensajes de WhatsApp**
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    # Inicializar respuesta de Twilio
    resp = MessagingResponse()
    msg = resp.message()
    respuesta = "No entendí tu mensaje. ¿Puedes reformularlo? 😊"

    # Obtener historial en Redis
    historial = redis_client.get(sender) or ""

    # **Flujo de reserva de citas**
    if "cita" in incoming_msg or "reservar" in incoming_msg:
        redis_client.set(sender + "_estado", "esperando_nombre", ex=1200)
        respuesta = "¡Genial! ¿Cuál es tu nombre completo? 😊"

    elif redis_client.get(sender + "_estado") == "esperando_nombre":
        redis_client.set(sender + "_nombre", incoming_msg, ex=1200)
        redis_client.set(sender + "_estado", "esperando_telefono", ex=1200)
        respuesta = "Gracias. Ahora dime tu número de teléfono 📞."

    elif redis_client.get(sender + "_estado") == "esperando_telefono":
        redis_client.set(sender + "_telefono", incoming_msg, ex=1200)
        redis_client.set(sender + "_estado", "esperando_fecha", ex=1200)
        respuesta = "¿Qué día prefieres para tu cita? 📅 (Ejemplo: '2025-02-12')"

    elif redis_client.get(sender + "_estado") == "esperando_fecha":
        redis_client.set(sender + "_fecha", incoming_msg, ex=1200)
        redis_client.set(sender + "_estado", "esperando_hora", ex=1200)
        respuesta = "Genial. ¿A qué hora te gustaría la cita? ⏰ (Ejemplo: '16:00')"

    elif redis_client.get(sender + "_estado") == "esperando_hora":
        redis_client.set(sender + "_hora", incoming_msg, ex=1200)
        redis_client.set(sender + "_estado", "esperando_servicio", ex=1200)
        respuesta = "¿Qué tratamiento necesitas? 💉."

    elif redis_client.get(sender + "_estado") == "esperando_servicio":
        nombre = redis_client.get(sender + "_nombre")
        telefono = redis_client.get(sender + "_telefono")
        fecha = redis_client.get(sender + "_fecha")
        hora = redis_client.get(sender + "_hora")
        servicio = incoming_msg

        cliente_id, cliente_nombre = buscar_cliente(telefono) or crear_cliente(nombre, telefono)
        exito, mensaje = crear_cita(cliente_id, cliente_nombre, fecha, hora, servicio) if cliente_id else (False, "No pude registrar tu cita.")

        respuesta = mensaje

    msg.body(respuesta)
    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
