import os
import requests
import json
from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse

# Inicializar Flask
app = Flask(__name__)

# Variables de entorno (Render)
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL_CLIENTES = "https://api.koibox.cloud/api/clientes/"
KOIBOX_URL_CITAS = "https://api.koibox.cloud/api/agenda/"
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

HEADERS = {
    "X-Koibox-Key": KOIBOX_API_KEY,
    "Content-Type": "application/json",
}

# ✅ Función para verificar autenticación con Koibox
def verificar_autenticacion():
    response = requests.get(KOIBOX_URL_CLIENTES, headers=HEADERS)
    if response.status_code == 200:
        print("✅ Autenticación correcta. API Key funcionando.")
    else:
        print(f"❌ Error en autenticación: {response.status_code}")
        print(response.text)  # Para depuración

# 🏥 Función para buscar paciente en Koibox
def buscar_paciente(telefono):
    params = {"movil": telefono}
    response = requests.get(KOIBOX_URL_CLIENTES, headers=HEADERS, params=params)
    
    if response.status_code == 200:
        data = response.json()
        if data["count"] > 0:
            return data["results"][0]  # Devuelve el primer resultado
    return None

# ➕ Función para crear un nuevo paciente en Koibox
def crear_paciente(nombre, telefono):
    payload = {
        "nombre": nombre,
        "movil": telefono,
        "is_active": True
    }
    response = requests.post(KOIBOX_URL_CLIENTES, headers=HEADERS, json=payload)

    if response.status_code == 201:
        return response.json()  # Retorna datos del paciente creado
    else:
        print(f"❌ Error al crear paciente: {response.status_code}")
        print(response.text)
        return None

# 📅 Función para reservar cita en Koibox
def reservar_cita(cliente_id, servicio_id, fecha_hora):
    payload = {
        "cliente": cliente_id,
        "servicio": servicio_id,
        "fecha_hora": fecha_hora,
        "estado": "confirmada"
    }
    response = requests.post(KOIBOX_URL_CITAS, headers=HEADERS, json=payload)

    if response.status_code == 201:
        return response.json()
    else:
        print(f"❌ Error al reservar cita: {response.status_code}")
        print(response.text)
        return None

# 🤖 Webhook de Twilio WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    sender_phone = request.values.get("From", "").replace("whatsapp:", "")

    resp = MessagingResponse()
    msg = resp.message()

    if "cita" in incoming_msg.lower():
        # Verificar si el paciente ya existe
        paciente = buscar_paciente(sender_phone)

        if paciente:
            cliente_id = paciente["id"]
            msg.body(f"📅 Ya estás registrado, {paciente['nombre']}. ¿Qué día y hora deseas tu cita?")
        else:
            msg.body("No encuentro tu registro. ¿Cómo te llamas?")
            return str(resp)

    elif incoming_msg.lower().startswith("mi nombre es"):
        nombre = incoming_msg[12:].strip()
        nuevo_paciente = crear_paciente(nombre, sender_phone)
        
        if nuevo_paciente:
            msg.body(f"✅ Registrado correctamente, {nombre}. ¿Qué día y hora deseas tu cita?")
        else:
            msg.body("❌ Hubo un problema registrándote. Inténtalo de nuevo.")

    elif "quiero una cita el" in incoming_msg.lower():
        # Ejemplo: "Quiero una cita el 15 de febrero a las 10:00"
        detalles = incoming_msg.lower().replace("quiero una cita el", "").strip()
        paciente = buscar_paciente(sender_phone)

        if paciente:
            cliente_id = paciente["id"]
            servicio_id = 1  # Cambia esto según el servicio en Koibox
            nueva_cita = reservar_cita(cliente_id, servicio_id, detalles)

            if nueva_cita:
                msg.body(f"📆 Cita confirmada para {detalles}. ¡Te esperamos!")
            else:
                msg.body("❌ No pudimos agendar tu cita. Prueba otro horario.")
        else:
            msg.body("⚠️ No encontré tu registro. Dime primero tu nombre.")

    else:
        msg.body("👋 ¡Hola! Soy Gabriel, el asistente de Sonrisas Hollywood. Puedes escribir 'cita' para comenzar.")

    return str(resp)

# Ejecutar servidor
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
