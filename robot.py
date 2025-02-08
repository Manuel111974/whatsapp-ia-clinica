from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse
import openai
import os
import requests
import logging
from datetime import datetime, timedelta

app = Flask(__name__)

# Configuración de logs
logging.basicConfig(level=logging.DEBUG)

# API Keys desde Environment Variables en Render
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")

# Configurar OpenAI
openai.api_key = OPENAI_API_KEY

# 📌 Datos de la clínica
DIRECCION_CLINICA = "Calle Colón 48, Valencia"
GOOGLE_MAPS_URL = "https://g.co/kgs/Y1h3Tb9"

# 📌 Función para convertir fechas en formato legible
def interpretar_fecha(mensaje):
    hoy = datetime.today()

    if "hoy" in mensaje:
        return hoy.strftime("%Y-%m-%d")

    elif "mañana" in mensaje:
        return (hoy + timedelta(days=1)).strftime("%Y-%m-%d")

    elif "lunes" in mensaje:
        dias_hasta_lunes = (7 - hoy.weekday()) % 7
        if dias_hasta_lunes == 0:
            dias_hasta_lunes = 7
        fecha_obj = hoy + timedelta(days=dias_hasta_lunes)
        return fecha_obj.strftime("%Y-%m-%d")

    elif "martes" in mensaje:
        dias_hasta_martes = (8 - hoy.weekday()) % 7
        fecha_obj = hoy + timedelta(days=dias_hasta_martes)
        return fecha_obj.strftime("%Y-%m-%d")

    elif "miércoles" in mensaje or "miercoles" in mensaje:
        dias_hasta_miercoles = (9 - hoy.weekday()) % 7
        fecha_obj = hoy + timedelta(days=dias_hasta_miercoles)
        return fecha_obj.strftime("%Y-%m-%d")

    elif "jueves" in mensaje:
        dias_hasta_jueves = (10 - hoy.weekday()) % 7
        fecha_obj = hoy + timedelta(days=dias_hasta_jueves)
        return fecha_obj.strftime("%Y-%m-%d")

    elif "viernes" in mensaje:
        dias_hasta_viernes = (11 - hoy.weekday()) % 7
        fecha_obj = hoy + timedelta(days=dias_hasta_viernes)
        return fecha_obj.strftime("%Y-%m-%d")

    elif "sábado" in mensaje or "sabado" in mensaje:
        dias_hasta_sabado = (12 - hoy.weekday()) % 7
        fecha_obj = hoy + timedelta(days=dias_hasta_sabado)
        return fecha_obj.strftime("%Y-%m-%d")

    elif "domingo" in mensaje:
        dias_hasta_domingo = (13 - hoy.weekday()) % 7
        fecha_obj = hoy + timedelta(days=dias_hasta_domingo)
        return fecha_obj.strftime("%Y-%m-%d")

    return None  # No se encontró una fecha válida

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
    response = requests.post(url, json=datos, headers=headers, verify=False)

    if response.status_code == 201:
        return "✅ Cita agendada con éxito en Koibox."
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

    # 📍 Respuesta sobre la ubicación de la clínica
    if any(word in incoming_msg for word in ["dónde está", "ubicación", "dirección", "cómo llegar"]):
        msg.body(f"📍 Nuestra clínica Sonrisas Hollywood está en: {DIRECCION_CLINICA}\nGoogle Maps: {GOOGLE_MAPS_URL}")
        return Response(str(resp), status=200, mimetype="application/xml")

    # 📅 Si piden agendar una cita
    elif "cita" in incoming_msg or "quiero una cita" in incoming_msg:
        fecha = interpretar_fecha(incoming_msg)
        if fecha:
            msg.body("😊 Para agendar tu cita dime: \n\n1️⃣ Tu nombre completo \n2️⃣ Tu teléfono \n3️⃣ El servicio que deseas")
        else:
            msg.body("📅 Por favor, dime también la fecha en la que quieres la cita.")
        return Response(str(resp), status=200, mimetype="application/xml")

    # 📌 Si recibe los datos de la cita
    elif any(word in incoming_msg for word in ["botox", "relleno", "hilos", "ácido hialurónico", "ortodoncia"]):
        palabras = incoming_msg.split()
        if len(palabras) >= 3:
            nombre = palabras[0] + " " + palabras[1]  # Primeras dos palabras como nombre
            telefono = palabras[2]  # Tercera palabra como teléfono
            servicio = " ".join(palabras[3:])  # Resto como servicio
            fecha = interpretar_fecha(incoming_msg)

            if fecha:
                resultado = agendar_cita(nombre, telefono, servicio, fecha)
                msg.body(f"📆 {resultado}")
            else:
                msg.body("❌ No entendí la fecha. Dime un día específico para agendar.")
        else:
            msg.body("❌ No entendí bien los datos. Envíame: Nombre, Teléfono, Servicio y Fecha.")
        return Response(str(resp), status=200, mimetype="application/xml")

    # 📌 Consulta a OpenAI (para todo lo demás)
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
