import os
import redis
import requests
import logging
from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse

# Configurar logging
logging.basicConfig(level=logging.INFO)

# Configuración de Flask
app = Flask(__name__)

# Configuración de Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Configuración de Koibox API
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"

# Validación de API Key
if not KOIBOX_API_KEY:
    logging.error("🚨 No se encontró la API Key de Koibox en los enviroments.")
else:
    logging.info("✅ API Key de Koibox cargada correctamente.")

# -----------------------------
# 🔹 FUNCIONES DE KOIBOX 🔹
# -----------------------------

# 📌 Obtener disponibilidad de citas desde Koibox
def obtener_disponibilidad():
    headers = {"X-Koibox-Key": KOIBOX_API_KEY}
    try:
        response = requests.get(f"{KOIBOX_URL}/agenda/", headers=headers)
        if response.status_code == 200:
            citas = response.json()
            if isinstance(citas, list) and len(citas) > 0:
                return citas[:5]  # Solo mostramos las 5 primeras citas
            else:
                return None
        elif response.status_code == 403:
            logging.error("🚨 Permiso denegado en Koibox. Revisa los permisos de la API Key.")
            return None
        elif response.status_code == 401:
            logging.error("🚨 No autorizado. API Key incorrecta o falta en la cabecera.")
            return None
        else:
            logging.error(f"🚨 Error inesperado en Koibox: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logging.error(f"⚠️ Error conectando con Koibox: {e}")
        return None

# 📌 Crear una cita en Koibox
def crear_cita(cliente, fecha, hora, servicio_id):
    headers = {
        "X-Koibox-Key": KOIBOX_API_KEY,
        "Content-Type": "application/json"
    }
    
    datos_cita = {
        "cliente": cliente,
        "fecha": fecha,
        "hora_inicio": hora,
        "servicios": [{"id": servicio_id}]
    }

    try:
        response = requests.post(f"{KOIBOX_URL}/agenda/", headers=headers, json=datos_cita)
        if response.status_code == 200:
            return response.json()
        else:
            logging.error(f"🚨 Error creando cita en Koibox: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logging.error(f"⚠️ Error en la solicitud a Koibox: {e}")
        return None

# -----------------------------
# 🔹 RUTAS DEL SERVIDOR 🔹
# -----------------------------

# Página de estado
@app.route("/")
def home():
    return "✅ Gabriel está activo y funcionando correctamente."

# 📌 Webhook para recibir mensajes de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    # Inicializar respuesta de Twilio
    resp = MessagingResponse()
    msg = resp.message()

    # Manejo de memoria en Redis (historial de conversación)
    historial = redis_client.get(sender) or ""
    historial += f"\nUsuario: {incoming_msg}"

    logging.info(f"📩 Mensaje recibido de {sender}: {incoming_msg}")

    # -----------------------------
    # 🔹 RESPUESTAS INTELIGENTES 🔹
    # -----------------------------

    if "hola" in incoming_msg:
        respuesta = "¡Hola! Soy Gabriel, el asistente de Sonrisas Hollywood. ¿En qué puedo ayudarte?"

    elif "precio" in incoming_msg or "coste" in incoming_msg:
        respuesta = "💎 El diseño de sonrisa en composite tiene un precio medio de 2500€. ¿Te gustaría agendar una cita de valoración gratuita?"

    elif "botox" in incoming_msg:
        respuesta = "💉 Actualmente tenemos una oferta en Botox con Vistabel a 7€/unidad. ¿Quieres más información?"

    elif "cita" in incoming_msg or "agenda" in incoming_msg:
        citas = obtener_disponibilidad()
        if citas:
            respuesta = "📅 Estas son las próximas citas disponibles:\n"
            for c in citas:
                respuesta += f"📍 {c['fecha']} a las {c['hora_inicio']}\n"
            respuesta += "Por favor, responde con la fecha y hora que prefieras."
        else:
            respuesta = "No hay citas disponibles en este momento. ¿Quieres que te avisemos cuando haya disponibilidad?"

    elif "reservar" in incoming_msg:
        # Extraer datos de la cita (debería mejorarse con NLP)
        partes = incoming_msg.split()
        if len(partes) >= 4:
            cliente = sender  # WhatsApp number as client ID
            fecha = partes[1]
            hora = partes[2]
            servicio_id = partes[3]

            cita_creada = crear_cita(cliente, fecha, hora, servicio_id)
            if cita_creada:
                respuesta = f"✅ Cita reservada el {fecha} a las {hora}. ¡Te esperamos!"
            else:
                respuesta = "❌ No se pudo reservar la cita. Inténtalo de nuevo."

        else:
            respuesta = "Por favor, proporciona la fecha, hora y el servicio al reservar."

    elif "ubicación" in incoming_msg or "dónde están" in incoming_msg:
        respuesta = "📍 Nuestra clínica está en Calle Colón 48, Valencia. ¡Te esperamos!"

    else:
        respuesta = "🤖 No entendí tu mensaje. ¿Podrías reformularlo?"

    # Guardar conversación en Redis
    historial += f"\nGabriel: {respuesta}"
    redis_client.set(sender, historial, ex=3600)  # Expira en 1 hora

    msg.body(respuesta)
    return str(resp)

# -----------------------------
# 🔹 INICIAR SERVIDOR 🔹
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
