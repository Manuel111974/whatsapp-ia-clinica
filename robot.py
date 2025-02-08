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
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # Configurar en Render
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")  # Configurar en Render

# Configurar OpenAI
openai.api_key = OPENAI_API_KEY

# 📌 Ofertas actuales de Sonrisas Hollywood (SIN precios)
OFERTAS_CLINICA = [
    "🎉 Descuento en tratamientos de blanqueamiento dental.",
    "🌟 Promoción especial en diseño de sonrisa.",
    "💆 Consulta gratuita para nuevos pacientes en estética facial.",
]

# 📌 Función para consultar disponibilidad en Koibox
def verificar_disponibilidad():
    url = "https://api.koibox.es/v1/agenda/disponibilidad"
    headers = {"Authorization": f"Bearer {KOIBOX_API_KEY}"}
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        disponibilidad = response.json()
        return disponibilidad
    else:
        return None

# 📌 Función para agendar una cita en Koibox
def agendar_cita(nombre, telefono, servicio):
    url = "https://api.koibox.es/v1/agenda/citas"
    headers = {
        "Authorization": f"Bearer {KOIBOX_API_KEY}",
        "Content-Type": "application/json"
    }
    datos = {
        "nombre": nombre,
        "telefono": telefono,
        "servicio": servicio,
    }
    response = requests.post(url, json=datos, headers=headers)

    if response.status_code == 201:
        return "✅ Cita agendada con éxito. Te esperamos en Sonrisas Hollywood."
    else:
        return "❌ Hubo un problema al agendar la cita. Intenta más tarde."

# 📌 Webhook para recibir mensajes de WhatsApp
@app.route("/webhook", methods=["POST"])
def whatsapp_reply():
    logging.debug(f"🔍 Petición recibida de Twilio: {request.form}")

    incoming_msg = request.form.get("Body", "").strip().lower()
    sender_number = request.form.get("From")

    if not incoming_msg:
        return Response("<Response><Message>No se recibió mensaje.</Message></Response>",
                        status=200, mimetype="application/xml")

    print(f"📩 Mensaje recibido de {sender_number}: {incoming_msg}")

    resp = MessagingResponse()
    msg = resp.message()

    # 📌 Si pregunta por ofertas
    if "oferta" in incoming_msg or "promoción" in incoming_msg:
        ofertas_msg = "\n".join(OFERTAS_CLINICA)
        msg.body(f"📢 ¡Promociones de Sonrisas Hollywood!\n{ofertas_msg}\n📅 ¿Quieres agendar una cita?")

    # 📌 Si pregunta por disponibilidad
    elif "disponible" in incoming_msg or "agenda" in incoming_msg:
        disponibilidad = verificar_disponibilidad()
        if disponibilidad:
            msg.body("📅 Hay disponibilidad en la agenda. ¿Te gustaría agendar una cita?")
        else:
            msg.body("❌ No hay disponibilidad en este momento. Intenta más tarde.")

    # 📌 Si pide agendar cita
    elif "cita" in incoming_msg:
        msg.body("😊 Para agendar tu cita dime: \n\n1️⃣ Tu nombre completo \n2️⃣ Tu teléfono \n3️⃣ El servicio que deseas")

    # 📌 Si la IA recibe un mensaje con datos personales, no los procesa
    elif any(word in incoming_msg for word in ["dni", "dirección", "edad", "correo", "tarjeta"]):
        msg.body("⚠️ Por seguridad, no podemos procesar datos personales por WhatsApp. Llámanos para más información.")

    # 📌 Consulta general a OpenAI
    else:
        try:
            response = openai.ChatCompletion.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "Eres el asistente de Sonrisas Hollywood. No menciones precios en WhatsApp."},
                    {"role": "user", "content": incoming_msg}
                ]
            )
            respuesta_ia = response["choices"][0]["message"]["content"].strip()
            msg.body(respuesta_ia)

        except openai.error.OpenAIError as e:
            print(f"⚠️ Error con OpenAI: {e}")
            msg.body("❌ Error de sistema. Intenta más tarde.")

    logging.debug(f"📤 Respuesta enviada a Twilio: {str(resp)}")

    return Response(str(resp), status=200, mimetype="application/xml")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
