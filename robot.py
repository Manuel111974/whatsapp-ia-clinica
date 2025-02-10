import os
import logging
import requests
from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse

# Configurar logging
logging.basicConfig(level=logging.INFO)

# Inicializar Flask
app = Flask(__name__)

# Variables de entorno en Render
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_USER = os.getenv("KOIBOX_USER")
KOIBOX_PASSWORD = os.getenv("KOIBOX_PASSWORD")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
REDIS_URL = os.getenv("REDIS_URL")

# URL API de Koibox
KOIBOX_URL = "https://api.koibox.cloud/api/agenda/"

# Almacén temporal de usuarios en memoria
users_sessions = {}

### 🟢 RUTA PRINCIPAL ###
@app.route("/", methods=["GET"])
def home():
    return "✅ WhatsApp IA Clínica en funcionamiento", 200

### 🟢 WEBHOOK DE TWILIO PARA WHATSAPP ###
@app.route("/webhook", methods=["POST"])
def webhook():
    """ Recibe los mensajes de WhatsApp y responde con el asistente Gabriel. """
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender_number = request.values.get("From", "")

    # Iniciar respuesta de Twilio
    resp = MessagingResponse()
    msg = resp.message()

    logging.info(f"📩 Mensaje recibido de {sender_number}: {incoming_msg}")

    # Si el usuario dice "cita", se inicia el proceso de agendamiento
    if "cita" in incoming_msg:
        users_sessions[sender_number] = {}
        msg.body("📅 ¿Para qué día y hora deseas la cita? Formato: DD-MM-AAAA HH:MM")
        return str(resp)

    # Si el usuario ya inició la sesión, capturar la fecha
    if sender_number in users_sessions and "fecha" not in users_sessions[sender_number]:
        try:
            fecha_hora = incoming_msg.split()
            fecha = fecha_hora[0]  # Formato: DD-MM-AAAA
            hora = fecha_hora[1]  # Formato: HH:MM
            users_sessions[sender_number]["fecha"] = fecha
            users_sessions[sender_number]["hora"] = hora
            msg.body("🔍 ¿Qué tratamiento necesitas? Ejemplo: 'Botox', 'Diseño de sonrisa'")
            return str(resp)
        except:
            msg.body("⚠️ Formato incorrecto. Usa: DD-MM-AAAA HH:MM")
            return str(resp)

    # Capturar el tratamiento
    if sender_number in users_sessions and "tratamiento" not in users_sessions[sender_number]:
        users_sessions[sender_number]["tratamiento"] = incoming_msg.title()
        msg.body("👨‍⚕️ ¿Tienes un profesional preferido? (Escribe el nombre o 'No')")
        return str(resp)

    # Capturar el profesional
    if sender_number in users_sessions and "profesional" not in users_sessions[sender_number]:
        users_sessions[sender_number]["profesional"] = incoming_msg.title()
        msg.body("📌 Confirmando tu cita... un momento por favor.")

        # Llamar a la API de Koibox
        resultado = crear_cita_koibox(
            users_sessions[sender_number]["fecha"],
            users_sessions[sender_number]["hora"],
            users_sessions[sender_number]["tratamiento"],
            users_sessions[sender_number]["profesional"]
        )

        msg.body(resultado)
        del users_sessions[sender_number]  # Limpiar sesión del usuario
        return str(resp)

    msg.body("👋 ¡Hola! Soy Gabriel, el asistente de Sonrisas Hollywood. Puedes escribir 'cita' para reservar.")
    return str(resp)

### 🔹 FUNCIÓN PARA CREAR CITA EN KOIBOX ###
def crear_cita_koibox(fecha, hora, tratamiento, profesional):
    headers = {
        "X-Koibox-Key": KOIBOX_API_KEY,
        "Content-Type": "application/json"
    }
    
    data = {
        "fecha": fecha,
        "hora": hora,
        "servicio": tratamiento,
        "profesional": profesional
    }

    logging.info(f"📡 Enviando datos a Koibox: {data}")

    response = requests.post(KOIBOX_URL, json=data, headers=headers)

    if response.status_code == 201:
        logging.info("✅ Cita creada con éxito.")
        return f"✅ Tu cita ha sido creada para el {fecha} a las {hora}."
    else:
        error_msg = response.json() if response.content else "Respuesta vacía"
        logging.error(f"❌ Error al crear cita: {error_msg}")
        return f"❌ No se pudo reservar la cita. Intenta otro horario."

### 🔹 INICIAR SERVIDOR EN RENDER ###
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
