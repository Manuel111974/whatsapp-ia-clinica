import os
import redis
import requests
import openai
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from datetime import datetime, timedelta

# Configuración de Flask
app = Flask(__name__)

# Configuración de Redis (Memoria de Gabriel)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Configuración de Koibox API
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"
HEADERS = {
    "X-Koibox-Key": KOIBOX_API_KEY,
    "Content-Type": "application/json"
}

# **CONFIGURACIÓN DE OPENAI**
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("⚠️ ERROR: No se encontró la API KEY de OpenAI.")

openai.api_key = OPENAI_API_KEY

# Datos de la clínica
UBICACION_CLINICA = "📍 Calle Colón 48, Valencia."
GOOGLE_MAPS_LINK = "https://g.co/kgs/U5uMgPg"
OFERTAS_LINK = "https://www.facebook.com/share/18e8U4AJTN/?mibextid=wwXIfr"

# 📌 **Función para llamar a OpenAI y generar respuestas**
def consultar_openai(mensaje):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Eres Gabriel, el asistente de Sonrisas Hollywood. Responde de manera profesional y amable."},
                {"role": "user", "content": mensaje}
            ]
        )
        return response["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"⚠️ ERROR en OpenAI: {str(e)}")
        return "Lo siento, no pude procesar tu consulta en este momento. Inténtalo más tarde. 😊"

# 📩 **Webhook de WhatsApp**
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "").replace("whatsapp:", "")

    resp = MessagingResponse()
    msg = resp.message()

    estado_usuario = redis_client.get(sender + "_estado")
    nombre = redis_client.get(sender + "_nombre")
    telefono = redis_client.get(sender + "_telefono")
    fecha = redis_client.get(sender + "_fecha")
    hora = redis_client.get(sender + "_hora")
    servicio = redis_client.get(sender + "_servicio")

    # 📌 **Saludo y presentación**
    if incoming_msg in ["hola", "buenas", "qué tal", "hey"]:
        if nombre:
            msg.body(f"¡Hola de nuevo, {nombre}! 😊 ¿En qué puedo ayudarte hoy?")
        else:
            msg.body("¡Hola! 😊 Soy *Gabriel*, el asistente de *Sonrisas Hollywood*. ¿En qué puedo ayudarte?")
        return str(resp)

    # 📌 **Información sobre la clínica**
    if "qué es sonrisas hollywood" in incoming_msg or "quiénes sois" in incoming_msg:
        msg.body(
            "✨ *Sonrisas Hollywood* es una clínica especializada en *odontología estética* y *medicina estética*.\n"
            "Transformamos sonrisas con *carillas dentales, ortodoncia invisible, implantes y blanqueamiento avanzado*.\n"
            "También ofrecemos *medicina estética*, con tratamientos como *botox, ácido hialurónico e hilos tensores*.\n"
            f"📍 Estamos en {UBICACION_CLINICA}. ¿Te gustaría recibir más información sobre algún tratamiento? 😊"
        )
        return str(resp)

    # 📌 **Ubicación**
    if any(word in incoming_msg for word in ["dónde estáis", "ubicación", "cómo llegar"]):
        msg.body(f"{UBICACION_CLINICA}\n📌 *Google Maps*: {GOOGLE_MAPS_LINK}")
        return str(resp)

    # 📌 **Ofertas activas**
    if "oferta" in incoming_msg:
        msg.body(f"💰 *Consulta nuestras ofertas actuales aquí*: {OFERTAS_LINK} 📢")
        return str(resp)

    # 📌 **Recordatorio de citas**
    if "mi cita" in incoming_msg or "cuando tengo la cita" in incoming_msg:
        if fecha and hora and servicio:
            msg.body(f"📅 Tu próxima cita es el *{fecha}* a las *{hora}* para *{servicio}* 😊")
        else:
            msg.body("No encuentro ninguna cita registrada a tu nombre. ¿Quieres agendar una?")
        return str(resp)

    # 📌 **Reservar cita**
    if "cita" in incoming_msg or "reservar" in incoming_msg:
        redis_client.set(sender + "_estado", "esperando_nombre", ex=600)
        msg.body("¡Genial! Primero dime tu nombre completo 😊.")
        return str(resp)

    if estado_usuario == "esperando_nombre":
        redis_client.set(sender + "_nombre", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_telefono", ex=600)
        msg.body(f"Gracias, {incoming_msg}. Ahora dime tu número de teléfono 📞.")
        return str(resp)

    if estado_usuario == "esperando_servicio":
        redis_client.set(sender + "_servicio", incoming_msg, ex=600)
        msg.body(f"✅ ¡Tu cita para {servicio} ha sido registrada el {fecha} a las {hora}! 😊")
        return str(resp)

    # 📌 **Confirmación de citas 24h antes**
    hoy = datetime.now().strftime("%Y-%m-%d")
    fecha_recordatorio = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    if fecha == fecha_recordatorio:
        msg.body(f"📅 *Recordatorio de cita:* Mañana tienes cita a las *{hora}* para *{servicio}*.\n"
                 "¿Confirmas tu asistencia? Responde *Sí* o *No*.")

    # 📌 **Uso de OpenAI para responder cualquier otra consulta**
    respuesta_ia = consultar_openai(incoming_msg)
    msg.body(respuesta_ia)
    return str(resp)

# 🚀 **Lanzar la aplicación en Render**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)), debug=True)
