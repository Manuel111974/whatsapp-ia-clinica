import os
import requests
import json
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# Configuración de Flask
app = Flask(__name__)

# Configuración de Airtable
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY", "TU_AIRTABLE_TOKEN_AQUÍ")
BASE_ID = "appLzlE5aJOuFkSZb"  # Base ID de Airtable
TABLE_NAME = "tblhdHTMAwFxBxJly"  # ID de la tabla de clientes

HEADERS = {
    "Authorization": f"Bearer {AIRTABLE_API_KEY}",
    "Content-Type": "application/json"
}

# Configuración de Twilio para notificaciones a Manuel
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "TU_SID_AQUÍ")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "TU_TOKEN_AQUÍ")
TWILIO_WHATSAPP_NUMBER = "whatsapp:+14155238886"  # Número oficial de Twilio para WhatsApp
MANUEL_WHATSAPP_NUMBER = "whatsapp:+34XXXXXXXXX"  # Tu número de WhatsApp

# Información de Sonrisas Hollywood y Albane Clinic
INFO_CLINICA = {
    "horarios": "⏰ Estamos abiertos de lunes a viernes de 10:00 a 20:00 y sábados de 10:00 a 14:00.",
    "botox": "💉 El tratamiento de Botox cuesta 7€ por unidad y los resultados son visibles en pocos días.",
    "diseño de sonrisa": "😁 El diseño de sonrisa con carillas tiene un ticket medio de 2.500€. Usamos composite o porcelana.",
    "ortodoncia": "🦷 Trabajamos con Invisalign para ortodoncia invisible, cómodo y sin brackets.",
    "medicina estética": "✨ Ofrecemos rellenos con ácido hialurónico, lifting Radiesse, hilos tensores y más."
}

# Enviar notificación por WhatsApp cuando alguien solicita una cita
def enviar_notificacion_whatsapp(nombre, telefono, fecha, hora, interes):
    mensaje = f"📢 *Nueva solicitud de cita*\n👤 Nombre: {nombre}\n📞 Teléfono: {telefono}\n📅 Fecha: {fecha}\n⏰ Hora: {hora}\n💉 Interés: {interes}"
    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
    data = {
        "From": TWILIO_WHATSAPP_NUMBER,
        "To": MANUEL_WHATSAPP_NUMBER,
        "Body": mensaje
    }
    auth = (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    response = requests.post(url, data=data, auth=auth)
    return response.status_code == 201

# Buscar si el cliente ya existe en Airtable
def buscar_cliente(telefono):
    url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_NAME}?filterByFormula={{fldNjWFRNcriIDMqf}}='{telefono}'"
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        records = response.json().get("records", [])
        if records:
            return records[0]["id"]
    return None  # Cliente no encontrado

# Registrar nuevo cliente en Airtable
def registrar_cliente(nombre, telefono):
    url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_NAME}"
    data = {
        "records": [
            {
                "fields": {
                    "fldcn2z38hHOGgqaJ": nombre,  # Nombre completo
                    "fldNjWFRNcriIDMqf": telefono  # Teléfono
                }
            }
        ]
    }
    response = requests.post(url, headers=HEADERS, json=data)
    if response.status_code == 200:
        return response.json()["records"][0]["id"]
    else:
        print(f"❌ Error creando cliente: {response.json()}")
        return None

# Registrar cita en Airtable
def registrar_cita(cliente_id, fecha, hora, interes):
    url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_NAME}"
    data = {
        "records": [
            {
                "fields": {
                    "fldiD6bE8zo81NV5V": fecha,  # Fecha de la cita
                    "fldEXJhD63AXZ7IDw": hora,  # Hora de la cita
                    "fldho86SgoGpcLFjR": interes,  # Interés (tratamiento)
                    "fld311mgl9eXxHWIr": "Programada",  # Estado de la cita
                    "fldB9uItP4dHqDnCu": f"Interesado en: {interes}"  # Notas del paciente
                }
            }
        ]
    }
    response = requests.post(url, headers=HEADERS, json=data)
    return response.status_code == 200

# Webhook para recibir mensajes de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    # Inicializar respuesta de Twilio
    resp = MessagingResponse()
    msg = resp.message()

    # Respuestas sobre información de la clínica
    if incoming_msg in INFO_CLINICA:
        msg.body(INFO_CLINICA[incoming_msg])
        return str(resp)

    # Flujo de agendamiento de citas
    if "cita" in incoming_msg or "agendar" in incoming_msg:
        msg.body("¡Hola! 😊 Para agendar una cita, dime tu nombre completo.")
        return str(resp)

    elif sender.endswith("_esperando_nombre"):
        nombre = incoming_msg
        request.values["Nombre"] = nombre
        msg.body("Gracias. Ahora dime tu número de teléfono 📞.")
        return str(resp)

    elif sender.endswith("_esperando_telefono"):
        telefono = incoming_msg
        request.values["Telefono"] = telefono
        msg.body("¡Perfecto! Ahora dime qué fecha prefieres para la cita 📅 (Ejemplo: '12/02/2025').")
        return str(resp)

    elif sender.endswith("_esperando_fecha"):
        fecha = incoming_msg
        request.values["Fecha"] = fecha
        msg.body("Genial. ¿A qué hora te gustaría la cita? ⏰ (Ejemplo: '16:00').")
        return str(resp)

    elif sender.endswith("_esperando_hora"):
        hora = incoming_msg
        request.values["Hora"] = hora
        msg.body("¿Qué tratamiento te interesa? (Ejemplo: 'Botox', 'Diseño de sonrisa', 'Ortodoncia') 😁.")
        return str(resp)

    elif sender.endswith("_esperando_interes"):
        interes = incoming_msg
        nombre, telefono, fecha, hora = request.values.get("Nombre"), request.values.get("Telefono"), request.values.get("Fecha"), request.values.get("Hora")

        cliente_id = buscar_cliente(telefono) or registrar_cliente(nombre, telefono)
        if cliente_id and registrar_cita(cliente_id, fecha, hora, interes):
            enviar_notificacion_whatsapp(nombre, telefono, fecha, hora, interes)
            msg.body("✅ ¡Tu cita ha sido programada! Nos vemos pronto. 😊")
        else:
            msg.body("⚠️ Hubo un problema al registrar la cita. Inténtalo nuevamente.")

    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
