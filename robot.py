import os
import redis
import requests
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# Configuración de Flask
app = Flask(__name__)

# Configuración de Redis (memoria de Gabriel)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Configuración de Koibox API
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"
HEADERS = {
    "X-Koibox-Key": KOIBOX_API_KEY,
    "Content-Type": "application/json"
}

# ID de Gabriel en Koibox (Reemplazar con el real)
GABRIEL_USER_ID = 1  

# 📩 Webhook de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "").replace("whatsapp:", "")

    resp = MessagingResponse()
    msg = resp.message()

    estado_usuario = redis_client.get(sender + "_estado")

    # 📌 Saludos
    if incoming_msg in ["hola", "buenas", "qué tal", "hey"]:
        msg.body("¡Hola! 😊 Soy Gabriel, el asistente de Sonrisas Hollywood. ¿En qué puedo ayudarte?")
        return str(resp)

    # 📌 Información sobre ubicación
    if "dónde estáis" in incoming_msg or "ubicación" in incoming_msg:
        msg.body("📍 Nos encontramos en Calle Colón 48, Valencia. ¡Te esperamos! 😊")
        return str(resp)

    # 📌 Información sobre ofertas
    if "oferta" in incoming_msg or "promoción" in incoming_msg:
        msg.body("💰 Puedes ver nuestras ofertas aquí: https://www.facebook.com/share/18e8U4AJTN/?mibextid=wwXIfr 📢")
        redis_client.set(sender + "_mencion_oferta", "Sí", ex=600)
        return str(resp)

    # 📌 Flujo de citas
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

    if estado_usuario == "esperando_servicio":
        servicio = incoming_msg
        redis_client.set(sender + "_servicio", servicio, ex=600)

        # 📌 Guardar notas en Koibox
        nombre = redis_client.get(sender + "_nombre")
        telefono = redis_client.get(sender + "_telefono")
        fecha = redis_client.get(sender + "_fecha")
        hora = redis_client.get(sender + "_hora")
        mencion_oferta = redis_client.get(sender + "_mencion_oferta")

        notas = f"Solicitud de cita: {servicio}. Fecha: {fecha} - Hora: {hora}."
        if mencion_oferta:
            notas += " 📌 El paciente mencionó una oferta."

        cliente_id = buscar_cliente(telefono) or crear_cliente(nombre, telefono)
        if cliente_id:
            actualizar_notas(cliente_id, notas)
            msg.body(f"✅ ¡Tu cita para {servicio} ha sido registrada el {fecha} a las {hora}! 😊")
        else:
            msg.body("⚠️ No se pudo completar la cita. Por favor, intenta nuevamente.")

        return str(resp)

    # 📌 Respuesta por defecto
    msg.body("No entendí tu mensaje. ¿Podrías reformularlo? 😊")
    return str(resp)

# 🔍 Buscar cliente en Koibox
def buscar_cliente(telefono):
    telefono = telefono.strip().replace(" ", "").replace("-", "")
    url = f"{KOIBOX_URL}/clientes/"
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        clientes_data = response.json()
        for cliente in clientes_data.get("results", []):
            if cliente.get("movil") == telefono:
                return cliente.get("id")
    return None

# 🆕 Crear cliente en Koibox
def crear_cliente(nombre, telefono):
    datos_cliente = {"nombre": nombre, "movil": telefono, "notas": "Cliente registrado por Gabriel IA."}
    response = requests.post(f"{KOIBOX_URL}/clientes/", headers=HEADERS, json=datos_cliente)
    return response.json().get("id") if response.status_code == 201 else None

# 📝 Actualizar notas en Koibox
def actualizar_notas(cliente_id, notas):
    url = f"{KOIBOX_URL}/clientes/{cliente_id}/"
    response = requests.patch(url, headers=HEADERS, json={"notas": notas})
    return response.status_code == 200

# 🚀 Lanzar aplicación
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
