import os
import redis
import requests
import json
from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse

# Configuración de Flask
app = Flask(__name__)

# Configuración de Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Configuración de Koibox API
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"

HEADERS = {
    "X-Koibox-Key": KOIBOX_API_KEY,
    "Content-Type": "application/json"
}

# Función para obtener disponibilidad de citas en Koibox
def obtener_disponibilidad():
    try:
        response = requests.get(f"{KOIBOX_URL}/agenda/", headers=HEADERS)
        if response.status_code == 200:
            citas = response.json()
            if isinstance(citas, list) and len(citas) > 0:
                return citas[:5]  # Devolvemos las 5 primeras citas disponibles
            else:
                return None
        else:
            print(f"Error Koibox: {response.text}")
            return None
    except Exception as e:
        print(f"Error en Koibox: {e}")
        return None

# Función para crear una cita en Koibox
def crear_cita(nombre, telefono, fecha, hora, servicio_id):
    datos_cita = {
        "cliente": {
            "nombre": nombre,
            "movil": telefono
        },
        "fecha": fecha,
        "hora_inicio": hora,
        "servicios": [{"id": servicio_id}],
        "notas": "Cita agendada por Gabriel (IA)"
    }
    try:
        response = requests.post(f"{KOIBOX_URL}/agenda/", headers=HEADERS, json=datos_cita)
        if response.status_code == 201:
            return True, "✅ Cita creada correctamente. Te esperamos en la clínica."
        else:
            return False, f"⚠️ No se pudo agendar la cita: {response.text}"
    except Exception as e:
        return False, f"Error en Koibox: {e}"

# Ruta principal
@app.route("/")
def home():
    return "✅ Gabriel está activo y funcionando correctamente."

# Webhook para recibir mensajes de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    # Inicializar respuesta de Twilio
    resp = MessagingResponse()
    msg = resp.message()

    # Obtener historial del usuario en Redis
    historial = redis_client.get(sender) or ""
    historial += f"\nUsuario: {incoming_msg}"

    # Lógica de respuesta
    if "hola" in incoming_msg or "buenas" in incoming_msg:
        respuesta = "¡Hola! Soy Gabriel, el asistente de Sonrisas Hollywood 😃. ¿Cómo puedo ayudarte hoy?"

    elif "precio" in incoming_msg or "coste" in incoming_msg:
        respuesta = "El diseño de sonrisa en composite tiene un precio medio de 2500€. ¿Te gustaría agendar una cita de valoración gratuita?"

    elif "botox" in incoming_msg:
        respuesta = "Actualmente tenemos una oferta en Botox con Vistabel a 7€/unidad. ¿Quieres más información?"

    elif "cita" in incoming_msg or "agenda" in incoming_msg:
        citas = obtener_disponibilidad()
        if citas:
            respuesta = "📅 Estas son las próximas citas disponibles:\n"
            for c in citas:
                respuesta += f"📍 {c['fecha']} a las {c['hora_inicio']}\n"
            respuesta += "Responde con la fecha y hora que prefieras."
        else:
            respuesta = "❌ No hay citas disponibles en este momento. ¿Quieres que te avisemos cuando haya una?"

    elif "reservar" in incoming_msg or "quiero una cita" in incoming_msg:
        redis_client.set(sender + "_estado", "esperando_datos", ex=600)
        respuesta = "¡Genial! Por favor, dime tu nombre y tu número de teléfono 📞."

    elif redis_client.get(sender + "_estado") == "esperando_datos":
        datos = incoming_msg.split()
        if len(datos) < 2:
            respuesta = "Necesito tu nombre y número de teléfono. Ejemplo: 'María 666777888'"
        else:
            nombre = datos[0]
            telefono = datos[1]
            redis_client.set(sender + "_nombre", nombre, ex=600)
            redis_client.set(sender + "_telefono", telefono, ex=600)
            redis_client.set(sender + "_estado", "esperando_fecha", ex=600)
            respuesta = f"Gracias, {nombre}. Ahora dime la fecha que prefieres para tu cita (ejemplo: '10/02/2025')."

    elif redis_client.get(sender + "_estado") == "esperando_fecha":
        fecha = incoming_msg
        redis_client.set(sender + "_fecha", fecha, ex=600)
        redis_client.set(sender + "_estado", "esperando_hora", ex=600)
        respuesta = "Perfecto. ¿A qué hora te gustaría la cita? (Ejemplo: '16:00')."

    elif redis_client.get(sender + "_estado") == "esperando_hora":
        hora = incoming_msg
        nombre = redis_client.get(sender + "_nombre")
        telefono = redis_client.get(sender + "_telefono")
        fecha = redis_client.get(sender + "_fecha")

        exito, mensaje = crear_cita(nombre, telefono, fecha, hora, servicio_id=1)  # Ajusta el ID del servicio
        respuesta = mensaje

        redis_client.delete(sender + "_estado")
        redis_client.delete(sender + "_nombre")
        redis_client.delete(sender + "_telefono")
        redis_client.delete(sender + "_fecha")

    elif "ubicación" in incoming_msg or "dónde están" in incoming_msg:
        respuesta = "📍 Nuestra clínica está en Calle Colón 48, Valencia. ¡Te esperamos!"

    elif "gracias" in incoming_msg:
        respuesta = "¡De nada! 😊 Cualquier otra cosa en la que pueda ayudarte, dime."

    else:
        respuesta = "🤖 No entendí tu mensaje. ¿Podrías reformularlo?"

    # Guardar contexto en Redis
    historial += f"\nGabriel: {respuesta}"
    redis_client.set(sender, historial, ex=3600)  # Historial por 1 hora

    msg.body(respuesta)
    return str(resp)

# Iniciar aplicación Flask
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
