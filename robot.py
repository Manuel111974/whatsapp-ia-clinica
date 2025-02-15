import os
import redis
import requests
import json
from rapidfuzz import process
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

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

# ID de Gabriel en Koibox
GABRIEL_USER_ID = 1  # ⚠️ REEMPLAZAR con el ID correcto

# 📌 Información fija de la clínica
UBICACION_CLINICA = "Calle Colón 48, Valencia"
FACEBOOK_OFERTAS = "https://www.facebook.com/share/18e8U4AJTN/?mibextid=wwXIfr"

# 📌 Función para normalizar teléfonos
def normalizar_telefono(telefono):
    telefono = telefono.strip().replace(" ", "").replace("-", "")
    if not telefono.startswith("+34"):  
        telefono = "+34" + telefono
    return telefono

# 📩 Webhook de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    resp = MessagingResponse()
    msg = resp.message()

    estado_usuario = redis_client.get(sender + "_estado")

    # 📌 Respuestas flexibles a saludos
    saludos = ["hola", "buenas", "qué tal", "hey", "buenos días", "buenas noches"]
    if incoming_msg in saludos:
        msg.body("¡Hola! 😊 Soy Gabriel, el asistente de Sonrisas Hollywood. ¿En qué puedo ayudarte?")
        return str(resp)

    # 📌 Información de ubicación
    if "dónde estáis" in incoming_msg or "ubicación" in incoming_msg:
        msg.body(f"📍 Estamos ubicados en {UBICACION_CLINICA}. ¡Te esperamos! 😊")
        return str(resp)

    # 📌 Información de ofertas
    if "ofertas" in incoming_msg or "promoción" in incoming_msg:
        msg.body(f"💰 Puedes ver nuestras ofertas aquí: {FACEBOOK_OFERTAS} 📢")
        return str(resp)

    # 📌 Manejo de citas
    if "cita" in incoming_msg or "reservar" in incoming_msg:
        redis_client.set(sender + "_estado", "esperando_nombre", ex=600)
        msg.body("¡Genial! Primero dime tu nombre completo 😊.")
        return str(resp)

    if estado_usuario == "esperando_nombre":
        redis_client.set(sender + "_nombre", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_telefono", ex=600)
        msg.body(f"Gracias, {incoming_msg}. Ahora dime tu número de teléfono 📞.")
        return str(resp)

    if estado_usuario == "esperando_telefono":
        redis_client.set(sender + "_telefono", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_fecha", ex=600)
        msg.body("¡Perfecto! ¿Qué día prefieres? 📅 (Ejemplo: '2025-02-14')")
        return str(resp)

    if estado_usuario == "esperando_fecha":
        redis_client.set(sender + "_fecha", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_hora", ex=600)
        msg.body("Genial. ¿A qué hora te gustaría la cita? ⏰ (Ejemplo: '11:00')")
        return str(resp)

    if estado_usuario == "esperando_hora":
        redis_client.set(sender + "_hora", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_servicio", ex=600)
        msg.body("¿Qué tratamiento necesitas? (Ejemplo: 'Botox', 'Diseño de sonrisa') 💉.")
        return str(resp)

    # 📌 Respuesta por defecto si no entiende el mensaje
    msg.body("No entendí tu mensaje. ¿Podrías reformularlo? 😊")
    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
