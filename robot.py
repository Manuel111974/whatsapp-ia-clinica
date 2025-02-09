import os
import redis
import requests
from flask import Flask, request
from openai import OpenAI
from twilio.twiml.messaging_response import MessagingResponse

# Configuración de Flask
app = Flask(__name__)

# Configuración de Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Configuración de OpenAI GPT-4
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

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
            print(f"Error Koibox: {response.text}")
            return None
    except Exception as e:
        print(f"Error en Koibox: {e}")
        return None

# Función para generar respuestas con OpenAI GPT-4
def generar_respuesta(contexto):
    try:
        response = client.completions.create(
            model="gpt-4-turbo",
            messages=[
                {"role": "system", "content": "Eres Gabriel, el asistente virtual de Sonrisas Hollywood, una clínica de odontología estética y medicina estética en Valencia. Responde de manera cálida, amigable y profesional, como un asistente humano real."},
                {"role": "user", "content": contexto}
            ],
            max_tokens=150
        )
        return response.choices[0].message['content'].strip()
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

    # Lógica de respuestas con IA
    if estado_usuario == "esperando_datos":
        datos = incoming_msg.split()
        if len(datos) < 2:
            respuesta = "Voy a necesitar tu nombre y tu número de teléfono para reservar la cita 😊. Ejemplo: 'María 666777888'."
        else:
            nombre = datos[0]
            telefono = datos[1]
            redis_client.set(sender + "_nombre", nombre, ex=600)
            redis_client.set(sender + "_telefono", telefono, ex=600)
            redis_client.set(sender + "_estado", "esperando_fecha", ex=600)
            respuesta = f"¡Genial, {nombre}! Ahora dime qué fecha te viene mejor para la cita. Puedes escribirme algo como '10/02/2025' 📅."

    elif estado_usuario == "esperando_fecha":
        fecha = incoming_msg
        redis_client.set(sender + "_fecha", fecha, ex=600)
        redis_client.set(sender + "_estado", "esperando_hora", ex=600)
        respuesta = "Perfecto. ¿A qué hora te gustaría la cita? ⏰ Ejemplo: '16:00'."

    elif estado_usuario == "esperando_hora":
        hora = incoming_msg
        nombre = redis_client.get(sender + "_nombre")
        telefono = redis_client.get(sender + "_telefono")
        fecha = redis_client.get(sender + "_fecha")

        if not nombre or not telefono or not fecha:
            respuesta = "❌ Algo salió mal con los datos. Vamos a intentarlo de nuevo. Dime tu nombre y teléfono."
            redis_client.delete(sender + "_estado")
        else:
            exito, mensaje = crear_cita(nombre, telefono, fecha, hora, servicio_id=1)
            respuesta = mensaje
            redis_client.delete(sender + "_estado")
            redis_client.delete(sender + "_nombre")
            redis_client.delete(sender + "_telefono")
            redis_client.delete(sender + "_fecha")

    elif "cita" in incoming_msg or "agenda" in incoming_msg:
        citas = obtener_disponibilidad()
        if citas:
            respuesta = "Aquí tienes las próximas citas disponibles 📅:\n"
            for c in citas:
                respuesta += f"📍 {c['fecha']} a las {c['hora_inicio']}\n"
            respuesta += "Dime cuál prefieres y te la reservo 😊."
        else:
            respuesta = "Ahora mismo no tenemos citas disponibles, pero dime qué día prefieres y te avisaré en cuanto tengamos un hueco 📆."

    elif "precio" in incoming_msg or "coste" in incoming_msg:
        respuesta = "El diseño de sonrisa en composite tiene un precio medio de 2500€. Si quieres, te puedo agendar una cita de valoración gratuita. ¿Te interesa? 😊"

    elif "botox" in incoming_msg:
        respuesta = "El tratamiento con Botox Vistabel está a 7€/unidad 💉. Si quieres, podemos hacerte una valoración para personalizar el tratamiento. ¿Quieres reservar cita? 😊"

    elif "ubicación" in incoming_msg or "dónde están" in incoming_msg:
        respuesta = "📍 Nuestra clínica está en Calle Colón 48, Valencia. ¡Ven a vernos cuando quieras!"

    elif "gracias" in incoming_msg:
        respuesta = "¡De nada! 😊 Siempre aquí para ayudarte. Si necesitas algo más, dime."

    else:
        # Gabriel usará OpenAI para responder preguntas generales de manera natural
        contexto = f"Usuario: {incoming_msg}\nHistorial de conversación:\n{historial}"
        respuesta = generar_respuesta(contexto)

    # Guardar contexto en Redis
    historial += f"\nGabriel: {respuesta}"
    redis_client.set(sender, historial, ex=3600)

    msg.body(respuesta)
    return str(resp)

# Iniciar aplicación Flask
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
