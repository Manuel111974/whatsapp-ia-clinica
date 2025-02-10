import os
import requests
import json
from flask import Flask, request, jsonify
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

# Función para buscar si un cliente ya existe en Airtable
def buscar_cliente(telefono):
    url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_NAME}?filterByFormula={{fldNjWFRNcriIDMqf}}='{telefono}'"
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        records = response.json().get("records", [])
        if records:
            return records[0]["id"]  # Devuelve el ID del cliente en Airtable
    return None  # Cliente no encontrado

# Función para registrar un nuevo cliente en Airtable
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

# Función para registrar una cita en Airtable
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
        request.values["Interes"] = interes

        # Buscar o registrar cliente en Airtable
        nombre = request.values.get("Nombre")
        telefono = request.values.get("Telefono")
        fecha = request.values.get("Fecha")
        hora = request.values.get("Hora")

        cliente_id = buscar_cliente(telefono)
        if not cliente_id:
            cliente_id = registrar_cliente(nombre, telefono)

        if cliente_id:
            exito = registrar_cita(cliente_id, fecha, hora, interes)
            if exito:
                msg.body("✅ ¡Tu cita ha sido programada! Nos vemos pronto en la clínica. 😊")
            else:
                msg.body("⚠️ Hubo un problema al registrar la cita. Inténtalo nuevamente.")
        else:
            msg.body("⚠️ No se pudo registrar al paciente en Airtable.")

    else:
        msg.body("🤖 No entendí tu mensaje. ¿Podrías reformularlo?")
    
    return str(resp)

# Iniciar aplicación Flask
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
