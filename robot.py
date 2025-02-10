import os
import requests
import json
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from langdetect import detect  # Para detectar el idioma

# Configuración de Flask
app = Flask(__name__)

# Configuración de Twilio para enviar WhatsApp a Manuel
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "TU_SID_AQUÍ")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "TU_TOKEN_AQUÍ")
TWILIO_WHATSAPP_NUMBER = "whatsapp:+14155238886"  # Número de Twilio para WhatsApp
MANUEL_WHATSAPP_NUMBER = "whatsapp:+34684472593"  # Número de Manuel

# Configuración de Airtable
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY", "TU_API_KEY_AQUÍ")
AIRTABLE_BASE_ID = "appLzlE5aJOuFkSZb"
AIRTABLE_TABLE_NAME = "tblhdHTMAwFxBxJly"

# Diccionario de respuestas inteligentes
RESPUESTAS_FAQ = {
    "precio botox": "El precio por unidad de bótox en la clínica es de 7€.",
    "diseño de sonrisa": "En Sonrisas Hollywood, el ticket medio del diseño de sonrisa es de 2.500€.",
    "horario": "Abrimos de lunes a viernes de 9:00 a 20:00.",
    "ubicación": "Nos encontramos en Calle Colón 48, Valencia.",
    "teléfono": "Puedes contactarnos al 📞 656 656 656.",
    "promociones": "Actualmente tenemos una promoción en valoración de medicina estética gratuita.",
}

# Función para enviar WhatsApp a Manuel cuando un cliente pide una cita
def enviar_notificacion_whatsapp(nombre, telefono, fecha, hora, servicio):
    mensaje = (f"📢 *Nueva solicitud de cita*\n"
               f"👤 *Nombre:* {nombre}\n"
               f"📞 *Teléfono:* {telefono}\n"
               f"📅 *Fecha:* {fecha}\n"
               f"⏰ *Hora:* {hora}\n"
               f"💉 *Servicio:* {servicio}")

    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
    data = {
        "From": TWILIO_WHATSAPP_NUMBER,
        "To": MANUEL_WHATSAPP_NUMBER,
        "Body": mensaje
    }
    auth = (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    response = requests.post(url, data=data, auth=auth)
    return response.status_code == 201

# Función para registrar al cliente en Airtable
def registrar_cliente_airtable(nombre, telefono):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}", "Content-Type": "application/json"}
    data = {
        "records": [
            {"fields": {"Nombre Completo": nombre, "Teléfono de Contacto": telefono}}
        ]
    }
    response = requests.post(url, headers=headers, json=data)
    return response.status_code == 200

# Webhook para recibir mensajes de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    # Detectar idioma
    idioma = "es"
    try:
        idioma = detect(incoming_msg)
    except:
        pass

    # Inicializar respuesta de Twilio
    resp = MessagingResponse()
    msg = resp.message()

    # **Gestión de citas**
    if "cita" in incoming_msg or "agendar" in incoming_msg or "quiero una cita" in incoming_msg:
        msg.body("¡Hola! 😊 Para agendar una cita, dime tu nombre completo.")
        request.values["Estado"] = "esperando_nombre"
        return str(resp)

    estado = request.values.get("Estado", "")

    if estado == "esperando_nombre":
        request.values["Nombre"] = incoming_msg
        request.values["Estado"] = "esperando_telefono"
        msg.body("Gracias. Ahora dime tu número de teléfono 📞.")
        return str(resp)

    elif estado == "esperando_telefono":
        request.values["Telefono"] = incoming_msg
        request.values["Estado"] = "esperando_fecha"
        msg.body("¡Perfecto! Ahora dime la fecha de la cita (Ejemplo: '12/02/2025') 📅.")
        return str(resp)

    elif estado == "esperando_fecha":
        request.values["Fecha"] = incoming_msg
        request.values["Estado"] = "esperando_hora"
        msg.body("¿A qué hora te gustaría la cita? (Ejemplo: '16:00') ⏰")
        return str(resp)

    elif estado == "esperando_hora":
        request.values["Hora"] = incoming_msg
        request.values["Estado"] = "esperando_servicio"
        msg.body("¿Qué servicio te interesa? (Ejemplo: 'Botox', 'Diseño de sonrisa', 'Ortodoncia') 💉.")
        return str(resp)

    elif estado == "esperando_servicio":
        request.values["Servicio"] = incoming_msg
        nombre = request.values.get("Nombre")
        telefono = request.values.get("Telefono")
        fecha = request.values.get("Fecha")
        hora = request.values.get("Hora")
        servicio = request.values.get("Servicio")

        # Registrar cliente en Airtable
        if registrar_cliente_airtable(nombre, telefono):
            # Enviar notificación SOLO si es una cita
            enviar_notificacion_whatsapp(nombre, telefono, fecha, hora, servicio)
            msg.body("✅ ¡Gracias! Hemos registrado tu interés. En breve te contactaremos para coordinar tu cita.")
        else:
            msg.body("⚠️ No se pudo registrar la cita. Por favor, inténtalo de nuevo o llámanos.")

        request.values["Estado"] = ""  # Reiniciar flujo
        return str(resp)

    # **Responder preguntas frecuentes**
    for key, respuesta in RESPUESTAS_FAQ.items():
        if key in incoming_msg:
            msg.body(respuesta)
            return str(resp)

    # **Si el mensaje no se entiende**
    msg.body("Lo siento, no entendí tu mensaje. ¿Puedes reformularlo? 😊")
    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
