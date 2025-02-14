import os
import redis
import requests
import json
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# 🔹 Configuración de Flask
app = Flask(__name__)

# 🔹 Configuración de Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# 🔹 Configuración de Koibox API
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"

HEADERS = {
    "X-Koibox-Key": KOIBOX_API_KEY,
    "Content-Type": "application/json"
}

# 🔹 Información de la clínica
INFO_CLINICA = {
    "nombre": "Sonrisas Hollywood Valencia",
    "telefono": "618 44 93 32",
    "ubicacion": "https://g.co/kgs/U5uMgPg",
    "ofertas": "https://www.facebook.com/share/1BeQpVyja5/?mibextid=wwXIfr"
}

# 📩 Webhook de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    """Procesa mensajes de WhatsApp"""
    try:
        # 📌 Capturar mensaje recibido
        incoming_msg = request.values.get("Body", "").strip().lower()
        sender = request.values.get("From", "")

        # 📌 LOGS en consola para ver qué llega
        print(f"📩 Mensaje recibido de {sender}: {incoming_msg}")

        resp = MessagingResponse()
        msg = resp.message()

        estado_usuario = redis_client.get(sender + "_estado")

        # 📌 **Respuestas a saludos y mensajes casuales**
        saludos = ["hola", "buenas", "qué tal", "hey", "gabriel", "holaa", "saludos"]
        if any(saludo in incoming_msg for saludo in saludos):
            msg.body(f"¡Hola! 😊 Soy Gabriel, el asistente de {INFO_CLINICA['nombre']}. ¿En qué puedo ayudarte?\n\n"
                     "1️⃣ Reservar una cita 🗓️\n"
                     "2️⃣ Conocer nuestras ofertas 💰\n"
                     "3️⃣ Ubicación de la clínica 📍\n"
                     "4️⃣ Hablar con un humano 👩‍⚕️")
            return str(resp)

        agradecimientos = ["gracias", "ok", "vale"]
        if any(palabra in incoming_msg for palabra in agradecimientos):
            msg.body("¡De nada! Si necesitas algo más, aquí estoy. 😊")
            return str(resp)

        # 📌 **Información de la clínica**
        if "ubicación" in incoming_msg or "dónde están" in incoming_msg:
            msg.body(f"Nuestra clínica está en 📍 {INFO_CLINICA['ubicacion']}\n📞 Contacto: {INFO_CLINICA['telefono']}")
            return str(resp)

        if "oferta" in incoming_msg or "promoción" in incoming_msg:
            msg.body(f"Aquí puedes ver nuestras ofertas 🔥: {INFO_CLINICA['ofertas']}")
            return str(resp)

        # 📌 **Manejo de errores y respuestas alternativas**
        msg.body("No estoy seguro de qué necesitas 🤔. Por favor elige una opción:\n\n"
                 "1️⃣ Reservar una cita 🗓️\n"
                 "2️⃣ Conocer nuestras ofertas 💰\n"
                 "3️⃣ Ubicación de la clínica 📍\n"
                 "4️⃣ Hablar con un humano 👩‍⚕️")
        return str(resp)

    except Exception as e:
        print(f"❌ ERROR en webhook: {str(e)}")
        return "Error interno", 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
