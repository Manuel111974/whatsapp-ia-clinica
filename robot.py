import os
import redis
import requests
import logging
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# Configuración de Flask
app = Flask(__name__)

# Configuración de logs
logging.basicConfig(level=logging.INFO)

# Configuración de Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Configuración de Koibox API
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"

def obtener_disponibilidad():
    """Obtiene las próximas citas disponibles desde Koibox."""
    headers = {"X-Koibox-Key": KOIBOX_API_KEY}  # Se usa X-Koibox-Key en lugar de Authorization
    
    try:
        response = requests.get(f"{KOIBOX_URL}/citas", headers=headers)
        response.raise_for_status()  # Lanza un error si la respuesta no es 200
        
        citas = response.json()
        logging.info(f"📅 Citas obtenidas: {citas}")

        # Devolver solo las 5 primeras citas disponibles
        return citas[:5] if citas else None

    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Error al obtener citas de Koibox: {e}")
        return None

@app.route("/")
def home():
    return "Gabriel está activo y funcionando correctamente."

@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    # Inicializar respuesta de Twilio
    resp = MessagingResponse()
    msg = resp.message()

    # Recuperar historial del usuario
    historial = redis_client.get(sender) or ""
    historial += f"\nUsuario: {incoming_msg}"

    # Lógica de respuesta
    if "hola" in incoming_msg:
        respuesta = "¡Hola! Soy Gabriel, el asistente de Sonrisas Hollywood. ¿Cómo puedo ayudarte hoy?"

    elif "precio" in incoming_msg or "coste" in incoming_msg:
        respuesta = "El diseño de sonrisa en composite tiene un precio medio de 2500€. ¿Te gustaría agendar una cita de valoración gratuita?"

    elif "botox" in incoming_msg:
        respuesta = "Actualmente tenemos una oferta en Botox con Vistabel a 7€/unidad. ¿Quieres más información?"

    elif "cita" in incoming_msg or "agenda" in incoming_msg:
        citas = obtener_disponibilidad()
        if citas:
            respuesta = "Estas son las próximas citas disponibles:\n"
            for c in citas:
                respuesta += f"📅 {c['date']} a las {c['time']}\n"
            respuesta += "Por favor, responde con la fecha y hora que prefieras."
        else:
            respuesta = "No se encontraron citas disponibles en este momento. ¿Quieres que te avisemos cuando haya disponibilidad?"

    elif "ubicación" in incoming_msg or "dónde están" in incoming_msg:
        respuesta = "Nuestra clínica está en Calle Colón 48, Valencia. ¡Te esperamos! 📍"

    else:
        respuesta = "No entendí tu mensaje. ¿Podrías reformularlo? 😊"

    # Guardar contexto en Redis
    historial += f"\nGabriel: {respuesta}"
    redis_client.set(sender, historial, ex=3600)  # Expira en 1 hora

    msg.body(respuesta)
    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
