from flask import Flask, request, Response, session
from twilio.twiml.messaging_response import MessagingResponse
import openai
import os
import requests
import logging
import dateparser  # Para interpretar fechas en lenguaje natural
from langdetect import detect  # Para detectar el idioma del usuario

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "supersecretkey")  # Para mantener sesiones en Flask

# Configuración de logs
logging.basicConfig(level=logging.DEBUG)

# API Keys desde Environment Variables en Render
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")

# Configurar OpenAI
openai.api_key = OPENAI_API_KEY

# 📌 Dirección Fija de la Clínica
DIRECCION_CLINICA = "Calle Colón 48, Valencia"
GOOGLE_MAPS_URL = "https://g.co/kgs/Y1h3Tb9"

# 📌 Ofertas actuales de Sonrisas Hollywood
OFERTAS_CLINICA = [
    "Descuento en tratamientos de blanqueamiento dental.",
    "Promoción especial en diseño de sonrisa.",
    "Consulta gratuita para nuevos pacientes en medicina estética facial.",
]

# 📌 Función para consultar disponibilidad en Koibox
def verificar_disponibilidad():
    url = "https://api.koibox.es/v1/agenda/disponibilidad"
    headers = {"Authorization": f"Bearer {KOIBOX_API_KEY}"}
    
    try:
        response = requests.get(url, headers=headers, verify=False)  # ⚠️ Desactiva SSL temporalmente
        if response.status_code == 200:
            return response.json()
        return None
    except requests.RequestException as e:
        logging.error(f"Error al consultar disponibilidad en Koibox: {e}")
        return None

# 📌 Función para agendar una cita en Koibox
def agendar_cita(nombre, telefono, servicio, fecha):
    url = "https://api.koibox.es/v1/agenda/citas"
    headers = {
        "Authorization": f"Bearer {KOIBOX_API_KEY}",
        "Content-Type": "application/json"
    }
    datos = {
        "nombre": nombre,
        "telefono": telefono,
        "servicio": servicio,
        "fecha": fecha
    }
    
    try:
        response = requests.post(url, json=datos, headers=headers, verify=False)  # ⚠️ Desactiva SSL
        if response.status_code == 201:
            return "✅ Cita agendada con éxito. Te esperamos en Sonrisas Hollywood."
        return "❌ Hubo un problema al agendar la cita. Intenta más tarde."
    except requests.RequestException as e:
        logging.error(f"Error al agendar cita en Koibox: {e}")
        return "❌ Error al conectar con la agenda."

# 📌 Webhook para recibir mensajes de WhatsApp
@app.route("/webhook", methods=["POST"])
def whatsapp_reply():
    incoming_msg = request.form.get("Body", "").strip().lower()
    sender_number = request.form.get("From")
    
    # Guardamos la conversación en sesión para recordar los datos del usuario
    if sender_number not in session:
        session[sender_number] = {"nombre": None, "telefono": None, "servicio": None, "fecha": None}

    resp = MessagingResponse()
    msg = resp.message()

    # 📍 Si pregunta por la ubicación
    if "dónde están" in incoming_msg or "ubicación" in incoming_msg:
        msg.body(f"📍 Nuestra clínica está en {DIRECCION_CLINICA}.\n📌 Google Maps: {GOOGLE_MAPS_URL}")
    
    # 📢 Si pregunta por ofertas
    elif "oferta" in incoming_msg or "promoción" in incoming_msg:
        ofertas_msg = "\n".join(OFERTAS_CLINICA)
        msg.body(f"📢 ¡Promociones de Sonrisas Hollywood!\n{ofertas_msg}\n📅 ¿Quieres agendar una cita?")

    # 📅 Si pregunta por disponibilidad
    elif "disponible" in incoming_msg or "agenda" in incoming_msg:
        disponibilidad = verificar_disponibilidad()
        if disponibilidad:
            msg.body("📅 Hay disponibilidad en la agenda. ¿Te gustaría agendar una cita?")
        else:
            msg.body("❌ No hay disponibilidad en este momento. Intenta más tarde.")

    # 📆 Si pide agendar cita
    elif "cita" in incoming_msg:
        msg.body("😊 Para agendar tu cita dime:\n\n1️⃣ Tu nombre completo\n2️⃣ Tu teléfono\n3️⃣ El servicio que deseas\n4️⃣ La fecha y hora deseada")

    # 📌 Si envía datos de cita
    elif any(x in incoming_msg for x in ["botox", "ácido hialurónico", "diseño de sonrisa"]):
        datos = incoming_msg.split()
        if len(datos) >= 4:
            nombre, telefono, servicio, fecha = datos[0], datos[1], " ".join(datos[2:-1]), dateparser.parse(datos[-1])
            
            # Guardamos la cita en sesión
            session[sender_number]["nombre"] = nombre
            session[sender_number]["telefono"] = telefono
            session[sender_number]["servicio"] = servicio
            session[sender_number]["fecha"] = fecha.strftime("%Y-%m-%d %H:%M") if fecha else "Fecha inválida"

            respuesta_cita = agendar_cita(nombre, telefono, servicio, fecha)
            msg.body(respuesta_cita)
        else:
            msg.body("⚠️ No entendí los datos. Envíalos en el formato correcto:\n\n*Ejemplo:* Juan Pérez 612345678 Botox 10 de febrero a las 16:00")

    # 🔄 Si el usuario ya dio sus datos, pero no dijo la fecha
    elif session[sender_number]["nombre"] and not session[sender_number]["fecha"]:
        fecha = dateparser.parse(incoming_msg)
        if fecha:
            session[sender_number]["fecha"] = fecha.strftime("%Y-%m-%d %H:%M")
            respuesta_cita = agendar_cita(
                session[sender_number]["nombre"],
                session[sender_number]["telefono"],
                session[sender_number]["servicio"],
                session[sender_number]["fecha"]
            )
            msg.body(respuesta_cita)
        else:
            msg.body("⚠️ No entendí la fecha. Inténtalo de nuevo.")

    # 🌎 Detección de idioma
    else:
        idioma = detect(incoming_msg)
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": f"Eres Gabriel, el asistente de Sonrisas Hollywood. Responde en {idioma}."},
                      {"role": "user", "content": incoming_msg}]
        )
        msg.body(response["choices"][0]["message"]["content"].strip())

    return Response(str(resp), status=200, mimetype="application/xml")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
