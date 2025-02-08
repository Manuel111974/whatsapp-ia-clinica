from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse
import openai
import os
import requests
import logging
import langdetect  # Para detectar el idioma

app = Flask(__name__)

# Configuración de logs
logging.basicConfig(level=logging.DEBUG)

# API Keys desde Environment Variables en Render
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")  

# Configurar OpenAI
openai.api_key = OPENAI_API_KEY

# 📌 Ubicación fija de la clínica
UBICACION_CLINICA = "📍 Sonrisas Hollywood está en Calle Colón 48, Valencia.\nGoogle Maps: https://g.co/kgs/Y1h3Tb9"

# 📌 Almacén de sesiones para recordar datos de los usuarios temporalmente
sesiones = {}

# 📌 Función para detectar el idioma del mensaje
def detectar_idioma(texto):
    try:
        return langdetect.detect(texto)
    except:
        return "es"  # Por defecto, español

# 📌 Función para verificar disponibilidad en Koibox
def verificar_disponibilidad():
    url = "https://api.koibox.es/v1/agenda/disponibilidad"
    headers = {"Authorization": f"Bearer {KOIBOX_API_KEY}"}

    try:
        response = requests.get(url, headers=headers, verify=False)  

        if response.status_code == 200:
            disponibilidad = response.json()
            return "📅 Hay disponibilidad en la agenda. ¿Te gustaría agendar una cita?"
        else:
            return f"⚠️ Error en la API de Koibox ({response.status_code}). Intenta más tarde."

    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Error al conectar con Koibox: {e}")
        return "⚠️ Hubo un problema al verificar la disponibilidad. Intenta más tarde."

# 📌 Webhook para recibir mensajes de WhatsApp
@app.route("/webhook", methods=["POST"])
def whatsapp_reply():
    logging.debug(f"🔍 Petición recibida de Twilio: {request.form}")

    incoming_msg = request.form.get("Body", "").strip()
    sender_number = request.form.get("From")

    if not incoming_msg:
        return Response("<Response><Message>No se recibió mensaje.</Message></Response>", 
                        status=200, mimetype="application/xml")

    print(f"📩 Mensaje recibido de {sender_number}: {incoming_msg}")

    # 🔍 Detectar idioma del usuario
    idioma = detectar_idioma(incoming_msg)

    # 📌 Mensajes predefinidos según idioma
    MENSAJES = {
        "es": {
            "ubicacion": UBICACION_CLINICA,
            "cita": "😊 Para agendar tu cita dime:\n\n1️⃣ Tu nombre completo\n2️⃣ Tu teléfono\n3️⃣ El servicio que deseas\n4️⃣ La fecha y hora deseada",
            "error": "⚠️ Hubo un problema. Intenta más tarde."
        },
        "en": {
            "ubicacion": "📍 Sonrisas Hollywood is located at Calle Colón 48, Valencia.\nGoogle Maps: https://g.co/kgs/Y1h3Tb9",
            "cita": "😊 To schedule an appointment, please tell me:\n\n1️⃣ Your full name\n2️⃣ Your phone number\n3️⃣ The service you want\n4️⃣ The desired date and time",
            "error": "⚠️ There was a problem. Please try again later."
        },
        "fr": {
            "ubicacion": "📍 Sonrisas Hollywood est situé à Calle Colón 48, Valence.\nGoogle Maps: https://g.co/kgs/Y1h3Tb9",
            "cita": "😊 Pour prendre rendez-vous, veuillez me dire:\n\n1️⃣ Votre nom complet\n2️⃣ Votre numéro de téléphone\n3️⃣ Le service souhaité\n4️⃣ La date et l'heure souhaitées",
            "error": "⚠️ Il y a eu un problème. Veuillez réessayer plus tard."
        }
    }

    resp = MessagingResponse()
    msg = resp.message()

    # 📌 Si pregunta por disponibilidad
    if "disponible" in incoming_msg or "agenda" in incoming_msg:
        disponibilidad_msg = verificar_disponibilidad()
        msg.body(disponibilidad_msg)

    # 📌 Si pregunta por ubicación
    elif "dónde están" in incoming_msg or "ubicación" in incoming_msg or "where are you" in incoming_msg:
        msg.body(MENSAJES.get(idioma, MENSAJES["es"])["ubicacion"])

    # 📌 Si el usuario quiere agendar una cita
    elif "cita" in incoming_msg or "appointment" in incoming_msg:
        msg.body(MENSAJES.get(idioma, MENSAJES["es"])["cita"])
        sesiones[sender_number] = {}

    # 📌 Si es una consulta general
    else:
        try:
            response = openai.ChatCompletion.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": f"Eres Gabriel, el asistente de Sonrisas Hollywood. Responde en {idioma}."},
                    {"role": "user", "content": incoming_msg}
                ]
            )
            respuesta_ia = response["choices"][0]["message"]["content"].strip()
            msg.body(respuesta_ia)

        except openai.error.OpenAIError as e:
            print(f"⚠️ Error con OpenAI: {e}")
            msg.body(MENSAJES.get(idioma, MENSAJES["es"])["error"])

    logging.debug(f"📤 Respuesta enviada a Twilio: {str(resp)}")

    return Response(str(resp), status=200, mimetype="application/xml")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
