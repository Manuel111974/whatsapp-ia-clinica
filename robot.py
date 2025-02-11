import os
import json
import requests
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

app = Flask(__name__)

# 🔑 Configuración de credenciales desde variables de entorno en Render
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api/"
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

# 🏥 Cabecera de autenticación para Koibox
HEADERS = {
    "X-Koibox-Key": KOIBOX_API_KEY,
    "Content-Type": "application/json"
}

# 📌 1️⃣ Verifica si la clave API es válida
def validar_api_koibox():
    url = KOIBOX_URL + "api-key/me/"
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        return response.json()["is_active"]
    return False

# 📌 2️⃣ Busca un cliente en Koibox por su número de móvil
def buscar_cliente(movil):
    url = KOIBOX_URL + "cliente/"
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        clientes = response.json()
        for cliente in clientes:
            if cliente["movil"] == movil:
                return cliente["id"]
    return None

# 📌 3️⃣ Registra un nuevo cliente en Koibox
def registrar_cliente(nombre, movil):
    url = KOIBOX_URL + "cliente/"
    data = {
        "nombre": nombre,
        "movil": movil,
        "email": f"{movil}@example.com"  # Se asigna un email ficticio
    }
    response = requests.post(url, headers=HEADERS, json=data)
    if response.status_code == 201:
        return response.json()["id"]
    return None

# 📌 4️⃣ Crea una cita en Koibox
def crear_cita(cliente_id, fecha, hora_inicio, hora_fin, servicio_id):
    url = KOIBOX_URL + "agenda/"
    data = {
        "cliente": {"value": cliente_id},
        "fecha": fecha,
        "hora_inicio": hora_inicio,
        "hora_fin": hora_fin,
        "servicios": [{"id": servicio_id}],  # ID del servicio a agendar
        "is_notificada_por_whatsapp": True,  # Notificar por WhatsApp
    }
    response = requests.post(url, headers=HEADERS, json=data)
    return response.status_code == 201

# 📌 5️⃣ Manejador de mensajes de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender_number = request.values.get("From", "").replace("whatsapp:", "")

    response = MessagingResponse()
    msg = response.message()

    # 📍 Verificación de API de Koibox
    if not validar_api_koibox():
        msg.body("⚠️ Error: La API de Koibox no está activa. Contacta con soporte.")
        return str(response)

    if "cita" in incoming_msg:
        msg.body("📅 ¿Qué día y hora deseas tu cita? (Ejemplo: 14-02-2025 10:00)")
    elif "-" in incoming_msg and ":" in incoming_msg:
        fecha, hora_inicio = incoming_msg.split()
        hora_fin = f"{int(hora_inicio.split(':')[0]) + 1}:00"  # Se asume duración de 1h

        cliente_id = buscar_cliente(sender_number)
        if not cliente_id:
            msg.body("👤 No estás registrado. ¿Cuál es tu nombre?")
            return str(response)

        servicio_id = 58  # Se debe definir el ID del servicio correspondiente en Koibox
        if crear_cita(cliente_id, fecha, hora_inicio, hora_fin, servicio_id):
            msg.body(f"✅ Tu cita ha sido programada para el {fecha} a las {hora_inicio}.")
        else:
            msg.body("⚠️ Error al crear la cita. Inténtalo más tarde.")
    
    elif incoming_msg.isalpha():  # Si envía un nombre después de pedir el registro
        cliente_id = registrar_cliente(incoming_msg, sender_number)
        if cliente_id:
            msg.body("✅ Te has registrado con éxito. Ahora dime la fecha y hora de tu cita.")
        else:
            msg.body("⚠️ No se pudo completar el registro. Inténtalo más tarde.")

    else:
        msg.body("❓ No entiendo tu mensaje. Escribe 'cita' para reservar.")

    return str(response)

# 📌 Iniciar servidor
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
