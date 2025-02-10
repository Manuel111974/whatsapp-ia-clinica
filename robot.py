import os
import redis
import requests
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# Configuración de Flask
app = Flask(__name__)

# Configuración de Redis para memoria temporal
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Configuración de Twilio para WhatsApp
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "TU_SID_AQUÍ")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "TU_TOKEN_AQUÍ")
TWILIO_WHATSAPP_NUMBER = "whatsapp:+14155238886"
MANUEL_WHATSAPP_NUMBER = "whatsapp:+34684472593"

# Función para enviar WhatsApp a Manuel cuando alguien agenda una cita
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

# Webhook para recibir mensajes de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    sender = request.values.get("From", "")

    # **PREVENIR ERRORES DE MENSAJES VACÍOS**
    if not incoming_msg:
        return "No message body received.", 400

    # Inicializar respuesta de Twilio
    resp = MessagingResponse()
    msg = resp.message()
    respuesta = "No entendí tu mensaje. ¿Puedes reformularlo? 😊"  # Valor por defecto

    # Obtener estado del usuario en Redis
    estado_usuario = redis_client.get(sender + "_estado") or ""

    # **Flujo de agendamiento de citas**
    if estado_usuario == "esperando_nombre":
        redis_client.set(sender + "_nombre", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_telefono", ex=600)
        respuesta = f"Gracias, {incoming_msg} 😊. Ahora dime tu número de teléfono 📞."

    elif estado_usuario == "esperando_telefono":
        redis_client.set(sender + "_telefono", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_fecha", ex=600)
        respuesta = "¡Perfecto! Ahora dime la fecha que prefieres para la cita (Ejemplo: '12/02/2025') 📅."

    elif estado_usuario == "esperando_fecha":
        redis_client.set(sender + "_fecha", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_hora", ex=600)
        respuesta = "Genial. ¿A qué hora te gustaría la cita? (Ejemplo: '16:00') ⏰"

    elif estado_usuario == "esperando_hora":
        redis_client.set(sender + "_hora", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_servicio", ex=600)
        respuesta = "¿Qué servicio te interesa? (Ejemplo: 'Botox', 'Diseño de sonrisa', 'Ortodoncia') 💉."

    elif estado_usuario == "esperando_servicio":
        redis_client.set(sender + "_servicio", incoming_msg, ex=600)

        # **Recuperar datos almacenados**
        nombre = redis_client.get(sender + "_nombre")
        telefono = redis_client.get(sender + "_telefono")
        fecha = redis_client.get(sender + "_fecha")
        hora = redis_client.get(sender + "_hora")
        servicio = redis_client.get(sender + "_servicio")

        # **Enviar notificación SOLO si se completan todos los datos**
        if nombre and telefono and fecha and hora and servicio:
            enviado = enviar_notificacion_whatsapp(nombre, telefono, fecha, hora, servicio)
            if enviado:
                respuesta = "✅ ¡Gracias! Tu cita ha sido registrada correctamente. En breve te contactaremos."
            else:
                respuesta = "❌ Hubo un error al enviar la notificación. Inténtalo más tarde."

            # **Limpiar Redis**
            redis_client.delete(sender + "_estado")
            redis_client.delete(sender + "_nombre")
            redis_client.delete(sender + "_telefono")
            redis_client.delete(sender + "_fecha")
            redis_client.delete(sender + "_hora")
            redis_client.delete(sender + "_servicio")
        else:
            respuesta = "❌ Hubo un error con los datos. Vamos a intentarlo de nuevo. ¿Cómo te llamas? 😊"
            redis_client.set(sender + "_estado", "esperando_nombre", ex=600)

    # **Iniciar el flujo de citas**
    elif "cita" in incoming_msg or "quiero reservar" in incoming_msg:
        redis_client.set(sender + "_estado", "esperando_nombre", ex=600)
        respuesta = "¡Genial! Primero dime tu nombre completo 😊."

    # **Respuestas rápidas**
    elif "precio" in incoming_msg or "coste" in incoming_msg:
        respuesta = "El diseño de sonrisa en composite tiene un precio medio de 2500€. ¿Quieres que te agende una cita de valoración gratuita? 😊"

    elif "botox" in incoming_msg:
        respuesta = "El tratamiento con Botox Vistabel está a 7€/unidad 💉. ¿Quieres reservar una consulta gratuita? 😊"

    elif "ubicación" in incoming_msg or "dónde están" in incoming_msg:
        respuesta = "📍 Nuestra clínica está en Calle Colón 48, Valencia. ¡Te esperamos!"

    elif "gracias" in incoming_msg:
        respuesta = "¡De nada! 😊 Siempre aquí para ayudarte."

    # **Enviar la respuesta solo si hay contenido**
    if respuesta.strip():
        msg.body(respuesta)
    else:
        return "No valid response generated.", 400  # Prevenir error 14103

    return str(resp)

# Ruta principal para comprobar que el bot está activo
@app.route("/")
def home():
    return "✅ Gabriel está activo y funcionando correctamente."

# Iniciar aplicación Flask con Gunicorn
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
