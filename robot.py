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
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")  

# Configurar OpenAI
openai.api_key = OPENAI_API_KEY

# 📌 Ofertas actuales de Sonrisas Hollywood
OFERTAS_CLINICA = [
    "✨ Descuento en tratamientos de blanqueamiento dental.",
    "💎 Promoción especial en diseño de sonrisa.",
    "😊 Consulta gratuita para nuevos pacientes en medicina estética facial."
]

# 📌 Ubicación fija de la clínica
UBICACION_CLINICA = "📍 Sonrisas Hollywood está en Calle Colón 48, Valencia.\nGoogle Maps: https://g.co/kgs/Y1h3Tb9"

# 📌 Función para consultar disponibilidad en Koibox (CORREGIDA)
def verificar_disponibilidad():
    url = "https://api.koibox.es/v1/agenda/disponibilidad"
    headers = {"Authorization": f"Bearer {KOIBOX_API_KEY}"}

    try:
        response = requests.get(url, headers=headers, verify=False, allow_redirects=True)  # Se sigue la redirección

        if response.status_code == 200:
            disponibilidad = response.json()
            if disponibilidad:
                return "📅 Hay disponibilidad en la agenda. ¿Te gustaría agendar una cita?"
            else:
                return "❌ No hay citas disponibles en este momento. Intenta más tarde."

        elif response.status_code == 404:
            return "⚠️ Error: No se encontró la API de disponibilidad en Koibox."

        else:
            return f"⚠️ Error en la API de Koibox ({response.status_code}). Intenta más tarde."

    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Error al conectar con Koibox: {e}")
        return "⚠️ Hubo un problema al verificar la disponibilidad. Intenta más tarde."

# 📌 Función para agendar una cita en Koibox (CORREGIDA)
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
        response = requests.post(url, json=datos, headers=headers, verify=False, allow_redirects=True)  # Se sigue la redirección

        if response.status_code == 201:
            return f"✅ Cita confirmada para {nombre} el {fecha}. ¡Te esperamos en Sonrisas Hollywood! {UBICACION_CLINICA}"

        elif response.status_code == 404:
            return "⚠️ No se pudo agendar la cita porque el servicio no fue encontrado en Koibox."

        else:
            return f"❌ Error en Koibox ({response.status_code}): {response.text}"

    except requests.exceptions.RequestException as e:
        return f"⚠️ Error al conectar con Koibox: {str(e)}"

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
        disponibilidad_msg = verificar_disponibilidad()
        msg.body(disponibilidad_msg)

    # 📌 Si pide la ubicación
    elif "dónde están" in incoming_msg or "ubicación" in incoming_msg:
        msg.body(UBICACION_CLINICA)

    # 📌 Si quiere agendar una cita
    elif "cita" in incoming_msg:
        msg.body("😊 Para agendar tu cita dime:\n\n1️⃣ Tu nombre completo\n2️⃣ Tu teléfono\n3️⃣ El servicio que deseas\n4️⃣ La fecha y hora deseada")

    # 📌 Si la IA recibe un mensaje con datos personales, no los procesa
    elif any(word in incoming_msg for word in ["dni", "dirección", "edad", "correo", "tarjeta"]):
        msg.body("⚠️ Por seguridad, no podemos procesar datos personales por WhatsApp. Llámanos para más información.")

    # 📌 Si el usuario ya ha dado los datos, intenta agendar la cita
    elif len(incoming_msg.split()) > 3:  
        partes = incoming_msg.split()
        nombre = partes[0] + " " + partes[1]  
        telefono = partes[2]  
        servicio = " ".join(partes[3:-2])  
        fecha = " ".join(partes[-2:])  

        resultado_cita = agendar_cita(nombre, telefono, servicio, fecha)
        msg.body(resultado_cita)

    # 📌 Consulta general a OpenAI
    else:
        try:
            response = openai.ChatCompletion.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "Eres el asistente Gabriel de Sonrisas Hollywood. No menciones precios en WhatsApp."},
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
