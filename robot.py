from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse
import openai
import os
import requests
import logging

app = Flask(__name__)

# Configuración de logs
logging.basicConfig(level=logging.DEBUG)

# API Keys desde Environment Variables en Render
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
KOIBOX_USER = os.getenv("KOIBOX_USER")
KOIBOX_PASSWORD = os.getenv("KOIBOX_PASSWORD")

# Configurar OpenAI
openai.api_key = OPENAI_API_KEY

# 📌 Ofertas actuales de Sonrisas Hollywood
OFERTAS_CLINICA = [
    "✨ Descuento en tratamientos de blanqueamiento dental.",
    "🌟 Promoción especial en diseño de sonrisa.",
    "💆 Consulta gratuita para nuevos pacientes en Medicina Estética Facial."
]

# 🔹 Función para obtener Token de Koibox
def obtener_token_koibox():
    url = "https://api.koibox.cloud/auth"
    data = {"user": KOIBOX_USER, "password": KOIBOX_PASSWORD}
    response = requests.post(url, json=data)
    
    if response.status_code == 200:
        return response.json().get("token")
    else:
        return None

# 🔹 Función para consultar disponibilidad en Koibox
def verificar_disponibilidad():
    token = obtener_token_koibox()
    if not token:
        return None
    
    url = "https://api.koibox.cloud/v1/agenda/disponibilidad"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        return response.json()
    else:
        return None

# 🔹 Función para agendar cita en Koibox
def agendar_cita(nombre, telefono, servicio, fecha, hora):
    token = obtener_token_koibox()
    if not token:
        return "❌ No se pudo autenticar con Koibox."

    url = "https://api.koibox.cloud/v1/agenda/citas"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    datos = {
        "paciente": {"nombre": nombre, "telefono": telefono},
        "servicio": servicio,
        "fecha": fecha,
        "hora": hora
    }
    response = requests.post(url, json=datos, headers=headers)

    if response.status_code == 201:
        return "✅ Cita agendada con éxito. Te esperamos en Sonrisas Hollywood."
    else:
        return "❌ Hubo un problema al agendar la cita."

# 🔹 Webhook para recibir mensajes de WhatsApp
@app.route("/webhook", methods=["POST"])
def whatsapp_reply():
    logging.debug(f"🔍 Petición recibida de Twilio: {request.form}")

    incoming_msg = request.form.get("Body", "").strip().lower()
    sender_number = request.form.get("From")

    if not incoming_msg:
        return Response("<Response><Message>No se recibió mensaje.</Message></Response>", status=200, mimetype="application/xml")

    print(f"📩 Mensaje recibido de {sender_number}: {incoming_msg}")

    resp = MessagingResponse()
    msg = resp.message()

    # 🔹 Si pregunta por ofertas
    if "oferta" in incoming_msg or "promoción" in incoming_msg:
        ofertas_msg = "\n".join(OFERTAS_CLINICA)
        msg.body(f"📢 ¡Promociones de Sonrisas Hollywood!\n{ofertas_msg}\n📅 ¿Quieres agendar una cita?")

    # 🔹 Si pregunta por disponibilidad
    elif "disponible" in incoming_msg or "agenda" in incoming_msg:
        disponibilidad = verificar_disponibilidad()
        if disponibilidad:
            msg.body("📅 Hay disponibilidad en la agenda. ¿Te gustaría agendar una cita?")
        else:
            msg.body("❌ No hay disponibilidad en este momento. Intenta más tarde.")

    # 🔹 Si pide agendar cita
    elif "cita" in incoming_msg:
        msg.body("😊 Para agendar tu cita dime:\n\n1️⃣ Tu nombre completo \n2️⃣ Tu teléfono \n3️⃣ El servicio que deseas \n4️⃣ Fecha y hora preferida.")

    # 🔹 Si recibe datos personales
    elif any(word in incoming_msg for word in ["dni", "dirección", "edad", "correo", "tarjeta"]):
        msg.body("⚠️ Por seguridad, no podemos procesar datos personales por WhatsApp. Llámanos para más información.")

    # 🔹 Respuesta de OpenAI
    else:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": "Eres el asistente Gabriel de Sonrisas Hollywood."}, {"role": "user", "content": incoming_msg}]
        )
        msg.body(response["choices"][0]["message"]["content"].strip())

    return Response(str(resp), status=200, mimetype="application/xml")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
