import os
import redis
import requests
import json
from rapidfuzz import process
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# Configuración de Flask
app = Flask(__name__)

# Configuración de Redis (Memoria de Gabriel)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Configuración de Koibox API
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"

HEADERS = {
    "X-Koibox-Key": KOIBOX_API_KEY,
    "Content-Type": "application/json"
}

# 📌 Información fija de la clínica
UBICACION_CLINICA = "Calle Colón 48, Valencia"
FACEBOOK_OFERTAS = "https://www.facebook.com/share/18e8U4AJTN/?mibextid=wwXIfr"

# 📌 Función para normalizar teléfonos
def normalizar_telefono(telefono):
    telefono = telefono.strip().replace(" ", "").replace("-", "")
    if not telefono.startswith("+34"):  
        telefono = "+34" + telefono
    return telefono

# 📌 Guardar la cita en Koibox con notas
def guardar_cita_koibox(cliente_id, nombre, telefono, fecha, hora, servicio, notas):
    datos_cita = {
        "fecha": fecha,
        "hora_inicio": hora,
        "hora_fin": calcular_hora_fin(hora, 1),
        "titulo": servicio,
        "notas": notas,
        "cliente": {"value": cliente_id, "text": nombre, "movil": telefono},
        "estado": 1  # Estado de cita confirmada
    }
    
    response = requests.post(f"{KOIBOX_URL}/agenda/cita/", headers=HEADERS, json=datos_cita)
    
    if response.status_code == 201:
        return True, "✅ ¡Tu cita ha sido creada con éxito!"
    return False, f"⚠️ No se pudo agendar la cita: {response.text}"

# 📌 Calcular hora de finalización
def calcular_hora_fin(hora_inicio, duracion_horas):
    h, m = map(int, hora_inicio.split(":"))
    h += duracion_horas
    return f"{h:02d}:{m:02d}"

# 📩 Webhook de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    resp = MessagingResponse()
    msg = resp.message()

    estado_usuario = redis_client.get(sender + "_estado")

    # 📌 Respuestas flexibles a saludos
    saludos = ["hola", "buenas", "qué tal", "hey", "buenos días", "buenas noches"]
    if incoming_msg in saludos:
        msg.body("¡Hola! 😊 Soy Gabriel, el asistente de Sonrisas Hollywood. ¿En qué puedo ayudarte?")
        return str(resp)

    # 📌 Información de ubicación
    if "dónde estáis" in incoming_msg or "ubicación" in incoming_msg:
        msg.body(f"📍 Estamos en {UBICACION_CLINICA}. ¡Te esperamos! 😊")
        return str(resp)

    # 📌 Información de ofertas
    if "oferta" in incoming_msg or "promoción" in incoming_msg:
        redis_client.set(sender + "_ultima_oferta", incoming_msg, ex=600)
        msg.body(f"💰 Puedes ver nuestras ofertas aquí: {FACEBOOK_OFERTAS} 📢")
        return str(resp)

    # 📌 Manejo de citas
    if "cita" in incoming_msg or "reservar" in incoming_msg:
        redis_client.set(sender + "_estado", "esperando_nombre", ex=600)
        msg.body("¡Genial! Primero dime tu nombre completo 😊.")
        return str(resp)

    if estado_usuario == "esperando_nombre":
        redis_client.set(sender + "_nombre", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_telefono", ex=600)
        msg.body(f"Gracias, {incoming_msg}. Ahora dime tu número de teléfono 📞.")
        return str(resp)

    if estado_usuario == "esperando_telefono":
        redis_client.set(sender + "_telefono", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_fecha", ex=600)
        msg.body("¡Perfecto! ¿Qué día prefieres? 📅 (Ejemplo: '2025-02-14')")
        return str(resp)

    if estado_usuario == "esperando_fecha":
        redis_client.set(sender + "_fecha", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_hora", ex=600)
        msg.body("Genial. ¿A qué hora te gustaría la cita? ⏰ (Ejemplo: '11:00')")
        return str(resp)

    if estado_usuario == "esperando_hora":
        redis_client.set(sender + "_hora", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_servicio", ex=600)
        msg.body("¿Qué tratamiento necesitas? (Ejemplo: 'Botox', 'Diseño de sonrisa') 💉.")
        return str(resp)

    if estado_usuario == "esperando_servicio":
        redis_client.set(sender + "_servicio", incoming_msg, ex=600)

        nombre = redis_client.get(sender + "_nombre")
        telefono = redis_client.get(sender + "_telefono")
        fecha = redis_client.get(sender + "_fecha")
        hora = redis_client.get(sender + "_hora")
        servicio = redis_client.get(sender + "_servicio")
        ultima_oferta = redis_client.get(sender + "_ultima_oferta")

        notas = f"Cita registrada por Gabriel IA. Servicio: {servicio}. Oferta mencionada: {ultima_oferta}"

        cliente_id = normalizar_telefono(telefono)  # Simulación de búsqueda en Koibox

        if cliente_id:
            exito, mensaje = guardar_cita_koibox(cliente_id, nombre, telefono, fecha, hora, servicio, notas)
        else:
            exito, mensaje = False, "No pude registrar tu cita porque no se pudo crear el cliente."

        msg.body(mensaje)
        return str(resp)

    # 📌 Respuesta por defecto si no entiende el mensaje
    msg.body("No entendí tu mensaje. ¿Podrías reformularlo? 😊")
    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
