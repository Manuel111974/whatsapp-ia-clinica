import os
import redis
import requests
import openai
import logging
from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse

# Configuración de logging
logging.basicConfig(level=logging.INFO)

# Configuración de Flask
app = Flask(__name__)

# Configuración de Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Configuración de OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

# Configuración de Koibox API
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/v1"


def obtener_disponibilidad():
    """Obtiene disponibilidad de citas desde Koibox"""
    headers = {"Authorization": f"Bearer {KOIBOX_API_KEY}"}
    try:
        response = requests.get(f"{KOIBOX_URL}/appointments", headers=headers)
        if response.status_code == 200:
            citas = response.json()
            return citas[:5]  # Devolvemos las 5 primeras citas disponibles
        else:
            return None
    except Exception as e:
        logging.error(f"Error en Koibox: {e}")
        return None


def generar_respuesta(mensaje, historial):
    """Genera una respuesta con OpenAI usando el historial de la conversación"""
    prompt = f"""
    Eres Gabriel, el asistente virtual de Sonrisas Hollywood.
    Responde de forma amable, clara y profesional.

    Historial de conversación:
    {historial}

    Usuario: {mensaje}
    Gabriel:"""

    try:
        respuesta = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "system", "content": prompt}],
            max_tokens=150
        )
        return respuesta["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logging.error(f"Error con OpenAI: {e}")
        return "Lo siento, parece que hubo un error al procesar tu mensaje. ¿Podrías intentarlo de nuevo?"


@app.route("/")
def home():
    return "Gabriel está activo y funcionando correctamente."


@app.route("/webhook", methods=["POST"])
def webhook():
    """Maneja mensajes de WhatsApp y responde con IA y Koibox"""
    if not request.values:
        logging.warning("⚠️ Petición vacía recibida en /webhook")
        return "Petición inválida", 400

    sender = request.values.get("From", "")
    message = request.values.get("Body", "").strip()

    logging.info(f"📩 Mensaje recibido de {sender}: {message}")

    # Recuperar historial de conversación
    historial = redis_client.get(sender) or ""

    # Lógica para preguntas específicas antes de enviar a OpenAI
    if "cita" in message or "agenda" in message:
        citas = obtener_disponibilidad()
        if citas:
            respuesta = "Estas son las próximas citas disponibles:\n"
            for c in citas:
                respuesta += f"📅 {c['date']} a las {c['time']}\n"
            respuesta += "Responde con la fecha y hora que prefieras."
        else:
            respuesta = "No hay citas disponibles en este momento. ¿Quieres que te avisemos cuando haya disponibilidad?"

    elif "ubicación" in message or "dónde están" in message:
        respuesta = "Nuestra clínica está en Calle Colón 48, Valencia. ¡Te esperamos! 📍"

    elif "precio" in message or "coste" in message:
        respuesta = "El diseño de sonrisa en composite tiene un precio medio de 2500€. ¿Te gustaría agendar una cita de valoración gratuita?"

    elif "botox" in message:
        respuesta = "Actualmente tenemos una oferta en Botox con Vistabel a 7€/unidad. ¿Quieres más información?"

    else:
        # Generar respuesta con OpenAI si no es una consulta específica
        respuesta = generar_respuesta(message, historial)

    # Guardar contexto en Redis
    nuevo_historial = f"{historial}\nUsuario: {message}\nGabriel: {respuesta}"
    redis_client.set(sender, nuevo_historial, ex=3600)  # Expira en 1 hora

    # Responder a WhatsApp
    response = MessagingResponse()
    response.message(respuesta)

    return str(response)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
