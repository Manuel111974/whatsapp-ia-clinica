import os
import redis
import requests
import openai
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# Configuración de Flask
app = Flask(__name__)

# Configuración de Redis para memoria temporal
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Configuración de OpenAI con el nuevo modelo
openai.api_key = os.getenv("OPENAI_API_KEY")

# Configuración de Twilio
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = "whatsapp:+14155238886"
MANUEL_WHATSAPP_NUMBER = "whatsapp:+34684472593"

# 🔥 **Función para generar respuestas con OpenAI GPT-4-Turbo**
def generar_respuesta(mensaje_usuario, historial):
    prompt = f"""
    Eres Gabriel, el asistente virtual de Sonrisas Hollywood y Albane Clinic. 
    Responde de manera educada y profesional, ofreciendo información clara sobre tratamientos odontológicos y estéticos.

    Contexto de conversación previa:
    {historial}

    Usuario: {mensaje_usuario}
    Gabriel:
    """

    try:
        respuesta_openai = openai.ChatCompletion.create(
            model="gpt-4-turbo",  # 📌 CAMBIAMOS A GPT-4-TURBO
            messages=[{"role": "system", "content": prompt}],
            max_tokens=150,
            temperature=0.7
        )
        return respuesta_openai["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"Error con OpenAI: {e}")
        return "Lo siento, hubo un problema al generar la respuesta. ¿Puedes repetir tu consulta?"

# 🔥 **Función para enviar WhatsApp a Manuel cuando alguien pide cita**
def enviar_notificacion_whatsapp(nombre, telefono, fecha, hora, servicio):
    if not (nombre and telefono and fecha and hora and servicio):
        return False  # No enviar si hay datos vacíos

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

# **Webhook para recibir mensajes de WhatsApp**
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    sender = request.values.get("From", "")

    # Inicializar respuesta de Twilio
    resp = MessagingResponse()
    msg = resp.message()
    respuesta = "No entendí tu mensaje. ¿Puedes reformularlo? 😊"

    # Obtener historial del usuario en Redis
    historial = redis_client.get(sender) or ""

    # **Flujo de agendamiento de citas**
    if "cita" in incoming_msg or "reservar" in incoming_msg:
        redis_client.set(sender + "_estado", "esperando_nombre", ex=600)
        respuesta = "¡Genial! Primero dime tu nombre completo 😊."

    elif redis_client.get(sender + "_estado") == "esperando_nombre":
        redis_client.set(sender + "_nombre", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_telefono", ex=600)
        respuesta = f"Gracias, {incoming_msg} 😊. Ahora dime tu número de teléfono 📞."

    elif redis_client.get(sender + "_estado") == "esperando_telefono":
        redis_client.set(sender + "_telefono", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_fecha", ex=600)
        respuesta = "¡Perfecto! ¿Qué día prefieres? 📅 (Ejemplo: '12/02/2025')"

    elif redis_client.get(sender + "_estado") == "esperando_fecha":
        redis_client.set(sender + "_fecha", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_hora", ex=600)
        respuesta = "Genial. ¿A qué hora te gustaría la cita? ⏰ (Ejemplo: '16:00')"

    elif redis_client.get(sender + "_estado") == "esperando_hora":
        redis_client.set(sender + "_hora", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_servicio", ex=600)
        respuesta = "¿Qué tratamiento necesitas? (Ejemplo: 'Botox', 'Diseño de sonrisa') 💉."

    elif redis_client.get(sender + "_estado") == "esperando_servicio":
        redis_client.set(sender + "_servicio", incoming_msg, ex=600)

        nombre = redis_client.get(sender + "_nombre")
        telefono = redis_client.get(sender + "_telefono")
        fecha = redis_client.get(sender + "_fecha")
        hora = redis_client.get(sender + "_hora")
        servicio = redis_client.get(sender + "_servicio")

        if nombre and telefono and fecha and hora and servicio:
            enviar_notificacion_whatsapp(nombre, telefono, fecha, hora, servicio)
            respuesta = "✅ ¡Gracias! Tu cita ha sido registrada. Te contactaremos pronto."

    else:
        respuesta = generar_respuesta(incoming_msg, historial)

    msg.body(respuesta)
    redis_client.set(sender, historial + f"\nUsuario: {incoming_msg}\nGabriel: {respuesta}", ex=3600)

    return str(resp)

# **Ruta principal**
@app.route("/")
def home():
    return "✅ Gabriel está activo y funcionando correctamente."

# **Ejecutar aplicación Flask**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
