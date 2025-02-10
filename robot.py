import os
import requests
import json
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# Configuración de Flask
app = Flask(__name__)

# Configuración de Twilio para enviar WhatsApp a Manuel
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "TU_SID_AQUÍ")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "TU_TOKEN_AQUÍ")
TWILIO_WHATSAPP_NUMBER = "whatsapp:+14155238886"  # Número de Twilio para WhatsApp
MANUEL_WHATSAPP_NUMBER = "whatsapp:+34684472593"  # Número de Manuel

# Función para enviar notificación de WhatsApp a Manuel
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

# Webhook para recibir mensajes de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    # Inicializar respuesta de Twilio
    resp = MessagingResponse()
    msg = resp.message()

    # Flujo de agendamiento de citas
    if "cita" in incoming_msg or "agendar" in incoming_msg:
        msg.body("¡Hola! 😊 Para agendar una cita, dime tu nombre completo.")
        return str(resp)

    elif sender.endswith("_esperando_nombre"):
        nombre = incoming_msg
        request.values["Nombre"] = nombre
        msg.body("Gracias. Ahora dime tu número de teléfono 📞.")
        return str(resp)

    elif sender.endswith("_esperando_telefono"):
        telefono = incoming_msg
        request.values["Telefono"] = telefono
        msg.body("¡Perfecto! Ahora dime la fecha de la cita (Ejemplo: '12/02/2025') 📅.")
        return str(resp)

    elif sender.endswith("_esperando_fecha"):
        fecha = incoming_msg
        request.values["Fecha"] = fecha
        msg.body("¿A qué hora te gustaría la cita? (Ejemplo: '16:00') ⏰")
        return str(resp)

    elif sender.endswith("_esperando_hora"):
        hora = incoming_msg
        request.values["Hora"] = hora
        msg.body("¿Qué servicio te interesa? (Ejemplo: 'Botox', 'Diseño de sonrisa', 'Ortodoncia') 💉.")
        return str(resp)

    elif sender.endswith("_esperando_servicio"):
        servicio = incoming_msg
        nombre = request.values.get("Nombre")
        telefono = request.values.get("Telefono")
        fecha = request.values.get("Fecha")
        hora = request.values.get("Hora")

        # Enviar notificación a Manuel
        enviar_notificacion_whatsapp(nombre, telefono, fecha, hora, servicio)

        msg.body("✅ ¡Gracias! Hemos registrado tu interés. En breve te contactaremos para coordinar tu cita.")
        return str(resp)

    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
