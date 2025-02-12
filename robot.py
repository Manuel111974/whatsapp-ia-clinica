import os
import redis
import requests
import openai
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# Configuración de Flask
app = Flask(__name__)

# Configuración de Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Configuración de OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

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
                return citas[:5]  
            else:
                return None
        else:
            print(f"Error en Koibox: {response.text}")
            return None
    except Exception as e:
        print(f"Error en Koibox: {e}")
        return None

# Función para generar respuestas con OpenAI GPT-4
def generar_respuesta(contexto):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4-turbo",
            messages=[
                {"role": "system", "content": "Eres Gabriel, el asistente virtual de Sonrisas Hollywood, una clínica de odontología estética en Valencia. Responde de manera cálida, profesional y natural."},
                {"role": "user", "content": contexto}
            ],
            max_tokens=150
        )
        return response["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"Error en OpenAI: {e}")
        return "Lo siento, no puedo responder en este momento."

# Webhook para recibir mensajes de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    sender = request.values.get("From", "")

    # Inicializar respuesta de Twilio
    resp = MessagingResponse()
    msg = resp.message()

    # Obtener historial del usuario en Redis
    historial = redis_client.get(sender) or ""
    historial += f"\nUsuario: {incoming_msg}"

    estado_usuario = redis_client.get(sender + "_estado") or ""

    # Lógica de conversación con OpenAI
    if "cita" in incoming_msg or "agenda" in incoming_msg:
        citas = obtener_disponibilidad()
        if citas:
            respuesta = "Aquí tienes las próximas citas disponibles 📅:\n"
            for c in citas:
                respuesta += f"📍 {c['fecha']} a las {c['hora_inicio']}\n"
            respuesta += "Dime cuál prefieres y te la reservo 😊."
        else:
            respuesta = "Ahora mismo no tenemos citas disponibles, pero dime qué día prefieres y te avisaré en cuanto haya un hueco 📆."

    elif "precio" in incoming_msg or "coste" in incoming_msg:
        respuesta = "El diseño de sonrisa en composite tiene un precio medio de 2500€. ¿Quieres que te agende una cita de valoración gratuita? 😊"

    elif "botox" in incoming_msg:
        respuesta = "El tratamiento con Botox Vistabel está a 7€/unidad 💉. ¿Quieres una consulta para personalizar el tratamiento? 😊"

    elif "ubicación" in incoming_msg or "dónde están" in incoming_msg:
        respuesta = "📍 Nuestra clínica está en Calle Colón 48, Valencia. ¡Te esperamos!"

    elif "gracias" in incoming_msg:
        respuesta = "¡De nada! 😊 Siempre aquí para ayudarte."

    else:
        # Gabriel usa OpenAI para responder preguntas generales de manera natural
        contexto = f"Usuario: {incoming_msg}\nHistorial de conversación:\n{historial}"
        respuesta = generar_respuesta(contexto)

    # Guardar contexto en Redis
    historial += f"\nGabriel: {respuesta}"
    redis_client.set(sender, historial, ex=3600)

    msg.body(respuesta)
    return str(resp)

# Ruta principal de salud del bot
@app.route("/")
def home():
    return "✅ Gabriel está activo y funcionando correctamente."

# Iniciar aplicación Flask con Gunicorn
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
