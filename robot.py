from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse
import openai
import os
import requests
import logging
import re

app = Flask(__name__)

# Configuración de logs
logging.basicConfig(level=logging.DEBUG)

# API Keys desde Environment Variables en Render
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
KOIBOX_USER = os.getenv("KOIBOX_USER")
KOIBOX_PASSWORD = os.getenv("KOIBOX_PASSWORD")

# Configurar OpenAI
openai.api_key = OPENAI_API_KEY

# 📌 Función para autenticar en Koibox y obtener un token
def obtener_token_koibox():
    url = "https://api.koibox.es/api/auth/login"
    payload = {"username": KOIBOX_USER, "password": KOIBOX_PASSWORD}
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.post(url, json=payload, headers=headers, verify=False)
        if response.status_code == 200:
            token = response.json().get("token")
            logging.debug(f"✅ Token de Koibox obtenido correctamente")
            return token
        else:
            logging.error(f"❌ Error autenticando en Koibox: {response.status_code} - {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Error en la conexión con Koibox: {e}")
        return None

# 📌 Función para verificar disponibilidad en Koibox
def verificar_disponibilidad():
    token = obtener_token_koibox()
    if not token:
        return None

    url = "https://api.koibox.es/api/agenda/disponibilidad"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        response = requests.get(url, headers=headers, verify=False)
        if response.status_code == 200:
            disponibilidad = response.json()
            return disponibilidad
        else:
            logging.error(f"❌ Error obteniendo disponibilidad: {response.status_code} - {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Error en la conexión con Koibox: {e}")
        return None

# 📌 Función para agendar una cita en Koibox
def agendar_cita(nombre, telefono, servicio, fecha):
    token = obtener_token_koibox()
    if not token:
        return "❌ Error autenticando con Koibox."

    url = "https://api.koibox.es/api/agenda/citas"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    datos = {
        "nombre": nombre,
        "telefono": telefono,
        "servicio": servicio,
        "fecha": fecha
    }

    try:
        response = requests.post(url, json=datos, headers=headers, verify=False)
        if response.status_code == 201:
            return f"✅ Cita agendada con éxito para {nombre} el {fecha}. Te esperamos en Sonrisas Hollywood."
        else:
            logging.error(f"❌ Error agendando cita: {response.status_code} - {response.text}")
            return "❌ Hubo un problema al agendar la cita. Intenta más tarde."
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Error en la conexión con Koibox: {e}")
        return "❌ Error en el sistema. Intenta más tarde."

# 📌 Webhook para WhatsApp
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

    # 📌 Verificar disponibilidad en Koibox
    if "disponible" in incoming_msg or "agenda" in incoming_msg:
        disponibilidad = verificar_disponibilidad()
        if disponibilidad:
            msg.body("📅 Hay disponibilidad en la agenda. ¿Te gustaría agendar una cita?")
        else:
            msg.body("❌ No hay disponibilidad en este momento. Intenta más tarde.")

    # 📌 Preguntar por datos de la cita
    elif "cita" in incoming_msg:
        msg.body("😊 Para agendar tu cita dime: \n\n1️⃣ Tu nombre completo \n2️⃣ Tu teléfono \n3️⃣ El servicio que deseas \n4️⃣ La fecha y hora deseada")

    # 📌 Intentar detectar y agendar la cita automáticamente
    else:
        # Expresión regular para detectar datos de cita en el mensaje
        patron = re.search(r"([a-zA-Z\s]+)\s(\d{9})\s([\w\s]+)\s(\d{1,2}/\d{1,2}/\d{4} \d{2}:\d{2})", incoming_msg)
        
        if patron:
            nombre = patron.group(1).title()
            telefono = patron.group(2)
            servicio = patron.group(3).title()
            fecha = patron.group(4)

            confirmacion = agendar_cita(nombre, telefono, servicio, fecha)
            msg.body(confirmacion)
        
        else:
            try:
                response = openai.ChatCompletion.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": "Eres el asistente Gabriel de Sonrisas Hollywood. Solo agendas citas si se proporcionan nombre, teléfono, servicio y fecha."},
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
