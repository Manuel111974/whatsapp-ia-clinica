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
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # Configurada en Render
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")  # Asegúrate de configurarla en Render

# Configurar OpenAI
openai.api_key = OPENAI_API_KEY

# 📌 **Información de la clínica**
NOMBRE_CLINICA = "Sonrisas Hollywood"
UBICACION_CLINICA = "Calle Colón 48, Valencia"
GOOGLE_MAPS_LINK = "https://g.co/kgs/Y1h3Tb9"

# 📌 **Ofertas actuales** (sin precios)
OFERTAS_CLINICA = [
    "Descuento en tratamientos de blanqueamiento dental.",
    "Promoción especial en diseño de sonrisa.",
    "Consulta gratuita para nuevos pacientes en Medicina Estética Facial.",
]

# 📌 **Función para verificar disponibilidad en Koibox**
def verificar_disponibilidad():
    url = "https://api.koibox.es/v1/agenda/disponibilidad"
    headers = {"Authorization": f"Bearer {KOIBOX_API_KEY}"}

    try:
        response = requests.get(url, headers=headers, verify=False)  # Desactiva verificación SSL
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Error en la API de Koibox: {e}")
        return None

# 📌 **Función para agendar una cita en Koibox**
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

    try:
        response = requests.post(url, json=datos, headers=headers, verify=False)  # Desactiva verificación SSL
        if response.status_code == 201:
            return f"✅ Cita agendada con éxito en {NOMBRE_CLINICA}. Te esperamos en {UBICACION_CLINICA}."
        else:
            return "❌ Hubo un problema al agendar la cita. Intenta más tarde."
    except requests.exceptions.RequestException as e:
        logging.error(f"Error en la API de Koibox: {e}")
        return "❌ No se pudo conectar con el sistema de citas. Intenta más tarde."

# 📌 **Webhook para recibir mensajes de WhatsApp**
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

    # 📌 **Si preguntan por la ubicación**
    if "dónde están" in incoming_msg or "ubicación" in incoming_msg:
        msg.body(f"📍 Estamos en {UBICACION_CLINICA}. Puedes encontrarnos en Google Maps aquí: {GOOGLE_MAPS_LINK}")

    # 📌 **Si preguntan por ofertas**
    elif "oferta" in incoming_msg or "promoción" in incoming_msg:
        ofertas_msg = "\n".join(OFERTAS_CLINICA)
        msg.body(f"📢 ¡Promociones de {NOMBRE_CLINICA}!\n{ofertas_msg}\n📅 ¿Quieres agendar una cita?")

    # 📌 **Si preguntan por disponibilidad**
    elif "disponible" in incoming_msg or "agenda" in incoming_msg:
        disponibilidad = verificar_disponibilidad()
        if disponibilidad:
            msg.body("📅 Hay disponibilidad en la agenda. ¿Te gustaría agendar una cita?")
        else:
            msg.body("❌ No hay disponibilidad en este momento. Intenta más tarde.")

    # 📌 **Si piden agendar una cita**
    elif "cita" in incoming_msg:
        msg.body("😊 Para agendar tu cita dime: \n\n1️⃣ Tu nombre completo \n2️⃣ Tu teléfono \n3️⃣ El servicio que deseas")

    # 📌 **Si detecta datos sensibles, bloquea la respuesta**
    elif any(word in incoming_msg for word in ["dni", "dirección", "edad", "correo", "tarjeta"]):
        msg.body("⚠️ Por seguridad, no podemos procesar datos personales por WhatsApp. Llámanos para más información.")

    # 📌 **Si proporcionan los datos para agendar cita**
    elif any(char.isdigit() for char in incoming_msg) and len(incoming_msg.split()) > 3:
        partes = incoming_msg.split()
        nombre = " ".join(partes[:-2])
        telefono = partes[-2]
        servicio = partes[-1]
        confirmacion = agendar_cita(nombre, telefono, servicio)
        msg.body(confirmacion)

    # 📌 **Consulta general a OpenAI**
    else:
        try:
            response = openai.ChatCompletion.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": f"Hola, soy Gabriel, el asistente virtual de {NOMBRE_CLINICA}. No menciono precios en WhatsApp. Estoy aquí para ayudarte con información sobre Medicina Estética Facial y Odontología."},
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
