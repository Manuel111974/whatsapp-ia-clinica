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

# API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")

openai.api_key = OPENAI_API_KEY

# 📍 **Ubicación fija**
DIRECCION_CLINICA = "Calle Colón 48, Valencia, España"
LINK_GOOGLE_MAPS = "https://g.co/kgs/Y1h3Tb9"

# 💰 **Precios actualizados**
PRECIOS = {
    "carillas composite": "2.500 € por arcada o 4.500 € por ambas arcadas.",
    "botox": "Desde 7 € por unidad.",
    "ácido hialurónico": "Desde 350 € por vial."
}

# 🛠 **Memoria de conversación**
conversaciones = {}

# 📌 **Consulta disponibilidad en Koibox**
def verificar_disponibilidad():
    url = "https://api.koibox.cloud/agenda/disponibilidad"
    headers = {"Authorization": f"Bearer {KOIBOX_API_KEY}"}
    response = requests.get(url, headers=headers, verify=False)

    if response.status_code == 200:
        return response.json()
    return None

# 📌 **Agendar cita en Koibox**
def agendar_cita(nombre, telefono, servicio, fecha):
    url = "https://api.koibox.cloud/agenda/citas"
    headers = {"Authorization": f"Bearer {KOIBOX_API_KEY}", "Content-Type": "application/json"}
    datos = {"nombre": nombre, "telefono": telefono, "servicio": servicio, "fecha": fecha}
    response = requests.post(url, json=datos, headers=headers, verify=False)

    if response.status_code == 201:
        return f"✅ Cita confirmada para {nombre} el {fecha} para {servicio}. Te esperamos en {DIRECCION_CLINICA}."
    return "❌ No se pudo agendar la cita. Inténtalo más tarde."

# 📌 **Webhook para WhatsApp**
@app.route("/webhook", methods=["POST"])
def whatsapp_reply():
    logging.debug(f"🔍 Petición recibida de Twilio: {request.form}")

    incoming_msg = request.form.get("Body", "").strip().lower()
    sender_number = request.form.get("From")

    if not incoming_msg:
        return Response("<Response><Message>No se recibió mensaje.</Message></Response>", status=200, mimetype="application/xml")

    print(f"📩 Mensaje recibido de {sender_number}: {incoming_msg}")

    if sender_number not in conversaciones:
        conversaciones[sender_number] = {}

    resp = MessagingResponse()
    msg = resp.message()

    # 📌 **Detección automática de idioma**
    try:
        lang = detect(incoming_msg)
        if lang not in ["es", "en", "fr", "pt"]:
            lang = "es"
    except:
        lang = "es"

    # 📍 **Ubicación de la clínica**
    if any(word in incoming_msg for word in ["dónde estáis", "ubicación", "dirección"]):
        msg.body(f"📍 Estamos en {DIRECCION_CLINICA}. Aquí tienes nuestra ubicación en Google Maps: {LINK_GOOGLE_MAPS}")

    # 💰 **Consulta de precios**
    elif "cuánto cuesta" in incoming_msg or "precio" in incoming_msg:
        for tratamiento, precio in PRECIOS.items():
            if tratamiento in incoming_msg:
                msg.body(f"💰 El precio de {tratamiento} es {precio}. ¿Quieres agendar una cita?")
                break
        else:
            msg.body("💰 Indícame qué tratamiento deseas saber el precio y te lo diré.")

    # 📅 **Disponibilidad en agenda**
    elif "disponible" in incoming_msg or "agenda" in incoming_msg:
        disponibilidad = verificar_disponibilidad()
        if disponibilidad:
            msg.body("📅 Hay disponibilidad en la agenda. ¿Quieres agendar una cita?")
        else:
            msg.body("❌ No hay disponibilidad en este momento. Intenta más tarde.")

    # 📝 **Registro de datos para cita**
    elif "cita" in incoming_msg or "reservar" in incoming_msg:
        msg.body("😊 Para agendar tu cita dime:\n\n1️⃣ Tu nombre completo\n2️⃣ Tu teléfono\n3️⃣ El servicio que deseas\n4️⃣ La fecha y hora deseada")

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
            del conversaciones[sender_number]

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
