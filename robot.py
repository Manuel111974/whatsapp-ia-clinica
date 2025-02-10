import os
import redis
import requests
import openai
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# Configuración de Flask
app = Flask(__name__)

# Configuración de Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Configuración de OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

# Configuración de Twilio
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = "whatsapp:+14155238886"
MANUEL_WHATSAPP_NUMBER = "whatsapp:+34684472593"

# Configuración de Koibox API
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"

HEADERS = {
    "X-Koibox-Key": KOIBOX_API_KEY,
    "Content-Type": "application/json"
}

# ID del empleado "Gabriel Asistente IA" (buscar en Koibox)
GABRIEL_EMPLOYEE_ID = 12345  # 🔍 Reemplazar con el ID correcto

# 🔥 **Función para buscar cliente en Koibox**
def buscar_cliente(telefono):
    url = f"{KOIBOX_URL}/clientes/"
    response = requests.get(url, headers=HEADERS, params={"movil": telefono})

    if response.status_code == 200:
        clientes = response.json()
        if clientes and len(clientes) > 0:
            return clientes[0]["id_cliente"]  # Retorna el primer cliente encontrado
    return None

# 🔥 **Función para crear cliente en Koibox**
def crear_cliente(nombre, telefono):
    url = f"{KOIBOX_URL}/clientes/"
    datos_cliente = {
        "nombre": nombre,
        "movil": telefono
    }
    response = requests.post(url, headers=HEADERS, json=datos_cliente)

    if response.status_code == 201:
        return response.json().get("id_cliente")
    else:
        print(f"❌ Error creando cliente en Koibox: {response.text}")
        return None

# 🔥 **Función para crear cita en Koibox**
def crear_cita(cliente_id, fecha, hora, servicio_id=1):
    url = f"{KOIBOX_URL}/agenda/"
    datos_cita = {
        "cliente": cliente_id,
        "fecha": fecha,
        "hora_inicio": hora,
        "hora_fin": calcular_hora_fin(hora),  # 🔹 Función para calcular duración
        "servicios": [{"id": servicio_id}],
        "empleado": GABRIEL_EMPLOYEE_ID,
        "notas": "Cita agendada por Gabriel (IA)"
    }

    response = requests.post(url, headers=HEADERS, json=datos_cita)

    if response.status_code == 201:
        return True, "✅ ¡Tu cita ha sido creada con éxito!"
    else:
        print(f"❌ Error creando cita en Koibox: {response.text}")
        return False, f"⚠️ No se pudo agendar la cita: {response.text}"

# 🔥 **Función para calcular la hora de fin**
def calcular_hora_fin(hora_inicio):
    hora, minuto = map(int, hora_inicio.split(":"))
    hora_fin = f"{hora + 1}:{minuto:02d}"  # 🔹 Suma 1 hora por defecto
    return hora_fin

# 🔥 **Webhook para recibir mensajes de WhatsApp**
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    sender = request.values.get("From", "")

    # Inicializar respuesta de Twilio
    resp = MessagingResponse()
    msg = resp.message()
    
    estado_usuario = redis_client.get(sender + "_estado") or ""

    # **📌 Flujo de cita**
    if "cita" in incoming_msg or "reservar" in incoming_msg:
        redis_client.set(sender + "_estado", "esperando_nombre", ex=600)
        respuesta = "¡Genial! Primero dime tu nombre completo 😊."

    elif estado_usuario == "esperando_nombre":
        redis_client.set(sender + "_nombre", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_telefono", ex=600)
        respuesta = f"Gracias, {incoming_msg} 😊. Ahora dime tu número de teléfono 📞."

    elif estado_usuario == "esperando_telefono":
        redis_client.set(sender + "_telefono", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_fecha", ex=600)
        respuesta = "¡Perfecto! ¿Qué día prefieres? 📅 (Ejemplo: '2025-02-12')"

    elif estado_usuario == "esperando_fecha":
        redis_client.set(sender + "_fecha", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_hora", ex=600)
        respuesta = "Genial. ¿A qué hora te gustaría la cita? ⏰ (Ejemplo: '16:00')"

    elif estado_usuario == "esperando_hora":
        redis_client.set(sender + "_hora", incoming_msg, ex=600)

        # Obtener datos almacenados
        nombre = redis_client.get(sender + "_nombre")
        telefono = redis_client.get(sender + "_telefono")
        fecha = redis_client.get(sender + "_fecha")
        hora = redis_client.get(sender + "_hora")

        # **Paso 1: Verificar si el cliente ya existe en Koibox**
        cliente_id = buscar_cliente(telefono)

        if not cliente_id:
            cliente_id = crear_cliente(nombre, telefono)
        
        if cliente_id:
            exito, mensaje = crear_cita(cliente_id, fecha, hora)
            respuesta = mensaje
        else:
            respuesta = "❌ No se pudo registrar el cliente en Koibox. Inténtalo de nuevo."

        # Limpiar datos en Redis
        redis_client.delete(sender + "_estado")
        redis_client.delete(sender + "_nombre")
        redis_client.delete(sender + "_telefono")
        redis_client.delete(sender + "_fecha")
        redis_client.delete(sender + "_hora")

    else:
        respuesta = "No entendí tu mensaje. ¿Puedes reformularlo? 😊"

    msg.body(respuesta)
    return str(resp)

# **Ejecutar aplicación**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
