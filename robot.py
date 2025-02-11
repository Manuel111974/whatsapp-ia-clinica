import os
import redis
import requests
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# 📌 Configuración de Flask
app = Flask(__name__)

# 📌 Configuración de Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# 📌 Configuración de Koibox API
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"

HEADERS = {
    "X-Koibox-Key": KOIBOX_API_KEY,
    "Content-Type": "application/json"
}

# 📌 ID del empleado "Gabriel Asistente IA" en Koibox
GABRIEL_USER_ID = 1

# 📌 Webhook para WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        incoming_msg = request.values.get("Body", "").strip()
        sender = request.values.get("From", "")

        print(f"📩 Mensaje recibido de {sender}: {incoming_msg}")

        resp = MessagingResponse()
        msg = resp.message()
        estado = redis_client.get(sender + "_estado")

        if estado is None:
            redis_client.set(sender + "_estado", "inicio")
            estado = "inicio"

        if estado == "inicio":
            redis_client.set(sender + "_estado", "esperando_nombre")
            msg.body("¡Hola! Para agendar una cita, dime tu nombre completo 😊.")

        elif estado == "esperando_nombre":
            redis_client.set(sender + "_nombre", incoming_msg)
            redis_client.set(sender + "_estado", "esperando_telefono")
            msg.body(f"Gracias, {incoming_msg}. Ahora dime tu número de teléfono 📞.")

        elif estado == "esperando_telefono":
            redis_client.set(sender + "_telefono", incoming_msg)
            redis_client.set(sender + "_estado", "esperando_fecha")
            msg.body("¡Perfecto! ¿Qué día prefieres para la cita? 📅 (Ejemplo: '2025-02-12')")

        elif estado == "esperando_fecha":
            redis_client.set(sender + "_fecha", incoming_msg)
            redis_client.set(sender + "_estado", "esperando_hora")
            msg.body("¿A qué hora te gustaría la cita? ⏰ (Ejemplo: '16:00')")

        elif estado == "esperando_hora":
            redis_client.set(sender + "_hora", incoming_msg)
            redis_client.set(sender + "_estado", "esperando_servicio")
            msg.body("¿Qué tratamiento necesitas? 💉 (Ejemplo: 'Botox', 'Limpieza dental')")

        elif estado == "esperando_servicio":
            redis_client.set(sender + "_servicio", incoming_msg)

            nombre = redis_client.get(sender + "_nombre")
            telefono = redis_client.get(sender + "_telefono")
            fecha = redis_client.get(sender + "_fecha")
            hora = redis_client.get(sender + "_hora")
            servicio = redis_client.get(sender + "_servicio")

            print(f"👤 Cliente: {nombre} | ☎️ Teléfono: {telefono} | 📅 Fecha: {fecha} | ⏰ Hora: {hora} | 🏥 Servicio: {servicio}")

            cliente_id = buscar_cliente(telefono) or crear_cliente(nombre, telefono)

            if cliente_id:
                exito, mensaje = crear_cita(cliente_id, nombre, telefono, fecha, hora, servicio)
            else:
                exito, mensaje = False, "No pude registrar tu cita porque no se pudo crear el cliente."

            msg.body(mensaje)
            redis_client.delete(sender + "_estado")  # Reseteamos la conversación

        return str(resp)

    except Exception as e:
        print(f"⚠️ Error en webhook: {str(e)}")
        return "Error interno", 500

# 🚀 **Iniciar aplicación**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
