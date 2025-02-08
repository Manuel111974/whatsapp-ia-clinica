from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse
import openai
import os
import requests
import logging
from langdetect import detect
import dateparser

app = Flask(__name__)

# Configuración de logs
logging.basicConfig(level=logging.DEBUG)

# API Keys desde Environment Variables en Render
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")

# Configurar cliente OpenAI
openai.api_key = OPENAI_API_KEY

# 📍 **Ubicación fija y precisa de Sonrisas Hollywood**
DIRECCION_CLINICA = "Calle Colón 48, Valencia, España"
LINK_GOOGLE_MAPS = "https://g.co/kgs/Y1h3Tb9"

# 📌 **Ofertas actuales de Sonrisas Hollywood (sin precios)**
OFERTAS_CLINICA = [
    "✨ Descuento especial en blanqueamiento dental.",
    "💎 Diseño de sonrisa con materiales de alta calidad.",
    "🌟 Consulta gratuita en tratamientos de Medicina Estética Facial.",
]

# 📌 **Almacenar datos de conversación temporalmente**
conversaciones = {}

# 📌 **Función para consultar disponibilidad en Koibox**
def verificar_disponibilidad():
    url = "https://api.koibox.cloud/agenda/disponibilidad"
    headers = {"Authorization": f"Bearer {KOIBOX_API_KEY}"}
    response = requests.get(url, headers=headers, verify=False)

    if response.status_code == 200:
        return response.json()
    return None

# 📌 **Función para agendar cita en Koibox**
def agendar_cita(nombre, telefono, servicio, fecha):
    url = "https://api.koibox.cloud/agenda/citas"
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
    response = requests.post(url, json=datos, headers=headers, verify=False)

    if response.status_code == 201:
        return f"✅ Cita confirmada para {nombre} el {fecha} para {servicio}. Te esperamos en Sonrisas Hollywood en {DIRECCION_CLINICA}."
    return "❌ No se pudo agendar la cita. Inténtalo más tarde."

# 📌 **Webhook para recibir mensajes de WhatsApp**
@app.route("/webhook", methods=["POST"])
def whatsapp_reply():
    logging.debug(f"🔍 Petición recibida de Twilio: {request.form}")

    incoming_msg = request.form.get("Body", "").strip().lower()
    sender_number = request.form.get("From")

    if not incoming_msg:
        return Response("<Response><Message>No se recibió mensaje.</Message></Response>", status=200, mimetype="application/xml")

    print(f"📩 Mensaje recibido de {sender_number}: {incoming_msg}")

    # Inicializar conversación del usuario si no existe
    if sender_number not in conversaciones:
        conversaciones[sender_number] = {}

    resp = MessagingResponse()
    msg = resp.message()

    # 📌 **Detección automática de idioma**
    try:
        lang = detect(incoming_msg)
    except:
        lang = "es"  # Si no se detecta, responde en español

    # 📌 **Ubicación de la clínica**
    if "ubicación" in incoming_msg or "dirección" in incoming_msg:
        msg.body(f"📍 Nos encontramos en {DIRECCION_CLINICA}. Aquí tienes nuestra ubicación en Google Maps: {LINK_GOOGLE_MAPS}")

    # 📌 **Consulta de ofertas**
    elif "oferta" in incoming_msg or "promoción" in incoming_msg:
        ofertas_msg = "\n".join(OFERTAS_CLINICA)
        msg.body(f"📢 ¡Promociones de Sonrisas Hollywood!\n{ofertas_msg}\n📅 ¿Quieres agendar una cita?")

    # 📌 **Disponibilidad en agenda**
    elif "disponible" in incoming_msg or "agenda" in incoming_msg:
        disponibilidad = verificar_disponibilidad()
        if disponibilidad:
            msg.body("📅 Hay disponibilidad en la agenda. ¿Te gustaría agendar una cita?")
        else:
            msg.body("❌ No hay disponibilidad en este momento. Intenta más tarde.")

    # 📌 **Recepción de datos para cita**
    elif "cita" in incoming_msg or "reservar" in incoming_msg:
        msg.body("😊 Para agendar tu cita dime:\n\n1️⃣ Tu nombre completo\n2️⃣ Tu teléfono\n3️⃣ El servicio que deseas\n4️⃣ La fecha y hora deseada")

    # 📌 **Registro progresivo de datos**
    elif any(word in incoming_msg for word in ["botox", "relleno", "ácido hialurónico", "carillas", "implante"]):
        conversaciones[sender_number]["servicio"] = incoming_msg
        msg.body("📅 ¿Para qué fecha y hora deseas la cita?")

    elif any(word in incoming_msg for word in ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]):
        fecha_procesada = dateparser.parse(incoming_msg)
        if fecha_procesada:
            conversaciones[sender_number]["fecha"] = fecha_procesada.strftime("%Y-%m-%d %H:%M")
            msg.body("✅ ¡Fecha registrada! Ahora dime tu nombre y número de contacto.")

    elif sender_number in conversaciones and "servicio" in conversaciones[sender_number] and "fecha" in conversaciones[sender_number]:
        partes = incoming_msg.split(" ")
        if len(partes) >= 2:
            nombre = partes[0] + " " + partes[1]
            telefono = partes[-1]

            servicio = conversaciones[sender_number]["servicio"]
            fecha = conversaciones[sender_number]["fecha"]

            resultado = agendar_cita(nombre, telefono, servicio, fecha)
            msg.body(resultado)
            del conversaciones[sender_number]  # Limpiar datos tras agendar

        else:
            msg.body("❌ No he podido procesar tu nombre y teléfono. Intenta de nuevo.")

    # 📌 **Consulta general a OpenAI**
    else:
        try:
            response = openai.ChatCompletion.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": f"Eres Gabriel, el asistente de Sonrisas Hollywood. Responde en {lang}."},
                    {"role": "user", "content": incoming_msg}
                ]
            )
            respuesta_ia = response["choices"][0]["message"]["content"].strip()
            msg.body(respuesta_ia)

        except openai.error.OpenAIError as e:
            print(f"⚠️ Error con OpenAI: {e}")
            msg.body("❌ Error de sistema. Intenta más tarde.")

    return Response(str(resp), status=200, mimetype="application/xml")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
