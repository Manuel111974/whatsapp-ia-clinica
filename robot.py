import os
import logging
import requests
from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse

# Configuración de logs para depuración
logging.basicConfig(level=logging.INFO)

# Inicialización de Flask
app = Flask(__name__)

# Variables de entorno
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api/agenda/"

# Almacenar sesiones de usuarios temporalmente
users_sessions = {}

@app.route("/", methods=["GET"])
def home():
    return "✅ WhatsApp IA Clínica funcionando", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    """ Manejo de mensajes entrantes de WhatsApp. """
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender_number = request.values.get("From", "")

    # Iniciar respuesta de Twilio
    resp = MessagingResponse()
    msg = resp.message()

    logging.info(f"📩 Mensaje recibido de {sender_number}: {incoming_msg}")

    # Si el usuario pide "cita", reiniciar sesión
    if "cita" in incoming_msg:
        users_sessions[sender_number] = {"estado": "esperando_fecha"}
        msg.body("📅 ¿Para qué día y hora deseas la cita? Formato: DD-MM-AAAA HH:MM")
        return str(resp)

    # Verificar si el usuario ya inició una solicitud de cita
    if sender_number in users_sessions:
        session = users_sessions[sender_number]

        if session["estado"] == "esperando_fecha":
            try:
                fecha_hora = incoming_msg.split()
                fecha = fecha_hora[0]  # DD-MM-AAAA
                hora = fecha_hora[1]  # HH:MM
                session["fecha"] = fecha
                session["hora"] = hora
                session["estado"] = "esperando_tratamiento"
                msg.body("🔍 ¿Qué tratamiento necesitas? Ejemplo: 'Botox', 'Diseño de sonrisa'")
                return str(resp)
            except:
                msg.body("⚠️ Formato incorrecto. Usa: DD-MM-AAAA HH:MM")
                return str(resp)

        elif session["estado"] == "esperando_tratamiento":
            session["tratamiento"] = incoming_msg.title()
            session["estado"] = "esperando_profesional"
            msg.body("👨‍⚕️ ¿Tienes un profesional preferido? (Escribe el nombre o 'No')")
            return str(resp)

        elif session["estado"] == "esperando_profesional":
            session["profesional"] = incoming_msg.title()
            session["estado"] = "confirmando_cita"

            msg.body("📌 Confirmando tu cita... un momento por favor.")

            resultado = crear_cita_koibox(
                session["fecha"],
                session["hora"],
                session["tratamiento"],
                session["profesional"]
            )

            msg.body(resultado)
            del users_sessions[sender_number]  # Limpiar sesión después de agendar la cita
            return str(resp)

    # Si el usuario no ha iniciado una solicitud, mostrar mensaje inicial
    msg.body("👋 ¡Hola! Soy Gabriel, el asistente de Sonrisas Hollywood. Escribe 'cita' para reservar.")
    return str(resp)

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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
