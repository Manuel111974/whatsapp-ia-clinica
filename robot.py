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

# Configuración de OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

# Datos de la clínica
UBICACION_CLINICA = "📍 Calle Colón 48, Valencia."
GOOGLE_MAPS_LINK = "https://g.co/kgs/U5uMgPg"
OFERTAS_LINK = "https://www.facebook.com/share/18e8U4AJTN/?mibextid=wwXIfr"

# 📌 **Función para llamar a OpenAI con historial de conversación**
def consultar_openai(mensaje, sender):
    historial_key = f"historial:{sender}"
    historial = redis_client.lrange(historial_key, 0, 4)  # Últimos 5 mensajes
    historial.append(f"Usuario: {mensaje}")

    contexto = [
        {"role": "system", "content": (
            "Eres *Gabriel*, el asistente virtual de *Sonrisas Hollywood*. "
            "Tu tono debe ser profesional, cercano y amable. "
            "Brindas información sobre odontología estética, medicina estética y los servicios de la clínica. "
            "Respondes a preguntas generales sobre tratamientos, citas y ubicación. "
            "Si la pregunta es sobre precios, derivar al enlace de ofertas. "
            "Si no sabes la respuesta, redirige al equipo de atención de la clínica."
        )}
    ]

    for msg in historial:
        contexto.append({"role": "user", "content": msg})

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=contexto
        )
        respuesta_ia = response["choices"][0]["message"]["content"].strip()
        redis_client.lpush(historial_key, f"Gabriel: {respuesta_ia}")
        redis_client.ltrim(historial_key, 0, 4)  # Mantener últimos 5 mensajes
        redis_client.expire(historial_key, 3600)  # Expira en 1 hora
        return respuesta_ia
    except Exception as e:
        print(f"⚠️ ERROR en OpenAI: {str(e)}")
        return "Lo siento, no pude procesar tu consulta en este momento. Inténtalo más tarde. 😊"

# 📩 **Webhook de WhatsApp**
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    sender = request.values.get("From", "").replace("whatsapp:", "")

    resp = MessagingResponse()
    msg = resp.message()

    # 📌 **Casos especiales**
    if incoming_msg.lower() in ["hola", "buenas", "qué tal", "hey"]:
        msg.body("¡Hola! 😊 Soy *Gabriel*, el asistente virtual de *Sonrisas Hollywood*. ¿En qué puedo ayudarte?")
        return str(resp)

    if "ubicación" in incoming_msg.lower() or "cómo llegar" in incoming_msg.lower():
        msg.body(f"{UBICACION_CLINICA}\n📌 *Google Maps*: {GOOGLE_MAPS_LINK}")
        return str(resp)

    if "oferta" in incoming_msg.lower():
        msg.body(f"💰 *Consulta nuestras ofertas actuales aquí*: {OFERTAS_LINK} 📢")
        return str(resp)

    # 📌 **Consulta de cita**
    paciente_key = f"paciente:{sender}"
    estado_usuario, nombre, telefono, fecha, hora, servicio = redis_client.mget(
        f"{paciente_key}:estado",
        f"{paciente_key}:nombre",
        f"{paciente_key}:telefono",
        f"{paciente_key}:fecha",
        f"{paciente_key}:hora",
        f"{paciente_key}:servicio"
    )

    if incoming_msg.lower() in ["mi cita", "cuando tengo la cita"]:
        if fecha and hora and servicio:
            msg.body(f"📅 Tu próxima cita es el *{fecha}* a las *{hora}* para *{servicio}* 😊")
        else:
            msg.body("No encuentro ninguna cita registrada a tu nombre. ¿Quieres agendar una?")
        return str(resp)

    # 📌 **Reservar cita**
    if incoming_msg.lower() in ["cita", "reservar"]:
        redis_client.mset({f"{paciente_key}:estado": "esperando_nombre"})
        redis_client.expire(paciente_key, 600)
        msg.body("¡Genial! Primero dime tu nombre completo 😊.")
        return str(resp)

    # 📌 **Procesar respuestas de OpenAI**
    respuesta_ia = consultar_openai(incoming_msg, sender)
    msg.body(respuesta_ia)
    return str(resp)

# 🚀 **Lanzar la aplicación en Render**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)), debug=True)
