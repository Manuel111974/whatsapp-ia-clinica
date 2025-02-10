import os
import requests
import redis
from flask import Flask, request, jsonify, session
from twilio.twiml.messaging_response import MessagingResponse

# Configuración de Flask
app = Flask(__name__)
app.secret_key = "supersecretkey"

# Configuración de Redis para memoria de conversación
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Configuración de Twilio para WhatsApp
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "TU_SID_AQUÍ")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "TU_TOKEN_AQUÍ")
TWILIO_WHATSAPP_NUMBER = "whatsapp:+14155238886"
MANUEL_WHATSAPP_NUMBER = "whatsapp:+34684472593"

# Función para enviar WhatsApp a Manuel cuando alguien agenda una cita
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

    # Recuperar estado del usuario desde Redis
    estado = redis_client.get(sender + "_estado") or ""

    # **Flujo de agendamiento de citas**
    if "cita" in incoming_msg or "agendar" in incoming_msg or "quiero una cita" in incoming_msg:
        redis_client.set(sender + "_estado", "esperando_nombre", ex=600)
        msg.body("¡Hola! 😊 Para agendar una cita, dime tu nombre completo.")
        return str(resp)

    if estado == "esperando_nombre":
        redis_client.set(sender + "_nombre", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_telefono", ex=600)
        msg.body("Gracias. Ahora dime tu número de teléfono 📞.")
        return str(resp)

    elif estado == "esperando_telefono":
        redis_client.set(sender + "_telefono", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_fecha", ex=600)
        msg.body("¡Perfecto! Ahora dime la fecha de la cita (Ejemplo: '12/02/2025') 📅.")
        return str(resp)

    elif estado == "esperando_fecha":
        redis_client.set(sender + "_fecha", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_hora", ex=600)
        msg.body("¿A qué hora te gustaría la cita? (Ejemplo: '16:00') ⏰")
        return str(resp)

    elif estado == "esperando_hora":
        redis_client.set(sender + "_hora", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_servicio", ex=600)
        msg.body("¿Qué servicio te interesa? (Ejemplo: 'Botox', 'Diseño de sonrisa', 'Ortodoncia') 💉.")
        return str(resp)

    elif estado == "esperando_servicio":
        redis_client.set(sender + "_servicio", incoming_msg, ex=600)

        # Recuperar datos
        nombre = redis_client.get(sender + "_nombre")
        telefono = redis_client.get(sender + "_telefono")
        fecha = redis_client.get(sender + "_fecha")
        hora = redis_client.get(sender + "_hora")
        servicio = redis_client.get(sender + "_servicio")

        # Enviar notificación SOLO si se completa la cita
        enviar_notificacion_whatsapp(nombre, telefono, fecha, hora, servicio)

        msg.body("✅ ¡Gracias! Tu cita ha sido registrada correctamente. En breve te contactaremos.")

        # Limpiar memoria temporal
        redis_client.delete(sender + "_estado")
        redis_client.delete(sender + "_nombre")
        redis_client.delete(sender + "_telefono")
        redis_client.delete(sender + "_fecha")
        redis_client.delete(sender + "_hora")
        redis_client.delete(sender + "_servicio")

        return str(resp)

    # **Si el usuario escribe algo que no es una cita**
    msg.body("No estoy seguro de haber entendido. ¿Puedes reformularlo? 😊")
    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
