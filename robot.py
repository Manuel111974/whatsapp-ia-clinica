import os
import redis
import requests
import json
from rapidfuzz import process
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

# 🔍 **Buscar cliente en Koibox**
def buscar_cliente(telefono):
    url = f"{KOIBOX_URL}/clientes/"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        clientes = response.json().get("results", [])
        for cliente in clientes:
            if cliente.get("movil") == telefono:
                return cliente.get("id"), cliente.get("notas", "")
    return None, ""

# 📩 **Webhook de WhatsApp**
@app.route("/webhook", methods=["POST"])
def webhook():
    """Procesa mensajes de WhatsApp con una IA más inteligente"""
    try:
        incoming_msg = request.values.get("Body", "").strip().lower()
        sender = request.values.get("From", "").replace("whatsapp:", "")

        resp = MessagingResponse()
        msg = resp.message()

        estado_usuario = redis_client.get(sender + "_estado")
        nombre_usuario, notas_previas = buscar_cliente(sender)

        # 📌 LOG en consola para depuración
        print(f"📩 Mensaje recibido de {sender}: {incoming_msg}")

        # **Si el paciente ya ha sido atendido antes, Gabriel lo reconoce**
        if nombre_usuario:
            msg.body(f"¡Hola de nuevo! 😊 Veo que ya eres paciente de {INFO_CLINICA['nombre']}. ¿Cómo puedo ayudarte hoy?")
        else:
            msg.body(f"¡Hola! 😊 Soy Gabriel, el asistente de {INFO_CLINICA['nombre']}. ¿En qué puedo ayudarte?\n\n"
                     "1️⃣ Reservar una cita 🗓️\n"
                     "2️⃣ Conocer nuestras ofertas 💰\n"
                     "3️⃣ Ubicación de la clínica 📍\n"
                     "4️⃣ Hablar con un humano 👩‍⚕️")
            return str(resp)

        # 🔹 **Procesar opciones**
        if "cita" in incoming_msg or "reservar" in incoming_msg:
            redis_client.set(sender + "_estado", "esperando_fecha", ex=600)
            msg.body("Perfecto. ¿Para qué fecha deseas la cita? 📅 (Ejemplo: '2025-02-14')")
            return str(resp)

        if "ofertas" in incoming_msg:
            msg.body(f"Aquí puedes ver nuestras ofertas actuales 🔥: {INFO_CLINICA['ofertas']}")
            return str(resp)

        if "ubicación" in incoming_msg or "dónde están" in incoming_msg:
            msg.body(f"Nuestra clínica está en 📍 {INFO_CLINICA['ubicacion']}\n📞 Contacto: {INFO_CLINICA['telefono']}")
            return str(resp)

        if "humano" in incoming_msg or "hablar con alguien" in incoming_msg:
            msg.body(f"Puedes llamarnos al 📞 {INFO_CLINICA['telefono']} o enviarnos un mensaje directo. 😊")
            return str(resp)

        # 🔹 **Flujo de reserva de cita con memoria**
        if estado_usuario == "esperando_fecha":
            redis_client.set(sender + "_fecha", incoming_msg, ex=600)
            redis_client.set(sender + "_estado", "esperando_hora", ex=600)
            msg.body("¿A qué hora prefieres la cita? ⏰ (Ejemplo: '11:00')")
            return str(resp)

        if estado_usuario == "esperando_hora":
            redis_client.set(sender + "_hora", incoming_msg, ex=600)
            redis_client.set(sender + "_estado", "esperando_servicio", ex=600)
            msg.body("¿Qué tratamiento necesitas? (Ejemplo: 'Botox', 'Diseño de sonrisa') 💉.")
            return str(resp)

        if estado_usuario == "esperando_servicio":
            redis_client.set(sender + "_servicio", incoming_msg, ex=600)

            # Recuperar datos de la reserva
            fecha = redis_client.get(sender + "_fecha")
            hora = redis_client.get(sender + "_hora")
            servicio = redis_client.get(sender + "_servicio")

            # Guardar en las notas del paciente en Koibox
            notas = f"📅 Cita reservada: {fecha} a las {hora}\n🛠️ Tratamiento: {servicio}\n📍 Clínica: {INFO_CLINICA['nombre']}"
            msg.body(f"¡Tu cita ha sido registrada! 🎉\n\n{notas}")

            return str(resp)

        # 🔹 **Respuesta predeterminada si no se entiende el mensaje**
        msg.body("No entendí tu mensaje. ¿Podrías reformularlo? 😊")
        return str(resp)

    except Exception as e:
        print(f"⚠️ Error en el webhook: {str(e)}")
        return str(MessagingResponse().message("Hubo un problema técnico, intenta más tarde."))

# 🚀 **Ejecutar la app**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
