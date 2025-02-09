import os
import redis
import requests
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

# Función para obtener disponibilidad de citas
def obtener_disponibilidad():
    headers = {"X-Koibox-Key": KOIBOX_API_KEY}  # Cabecera correcta de autenticación
    try:
        response = requests.get(f"{KOIBOX_URL}/agenda/", headers=headers)

        # Verificar si la respuesta es exitosa
        if response.status_code == 200:
            citas = response.json()
            
            # Verificar si la respuesta es una lista antes de acceder a ella
            if isinstance(citas, list) and len(citas) > 0:
                return citas[:5]  # Tomar solo las primeras 5 citas disponibles
            else:
                print("La API no devolvió una lista de citas válidas.")
                return None
        else:
            print(f"Error al obtener citas: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Error en Koibox: {e}")
        return None

# Función para crear una cita en Koibox
def crear_cita(cliente, fecha, hora_inicio, hora_fin, servicio_id):
    headers = {
        "X-Koibox-Key": KOIBOX_API_KEY,
        "Content-Type": "application/json"
    }
    data = {
        "cliente": cliente,
        "fecha": fecha,
        "hora_inicio": hora_inicio,
        "hora_fin": hora_fin,
        "servicios": [{"id": servicio_id}]
    }

    try:
        response = requests.post(f"{KOIBOX_URL}/agenda/", json=data, headers=headers)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error al crear cita: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Error en Koibox: {e}")
        return None

# Webhook para recibir mensajes de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    # Inicializar respuesta de Twilio
    resp = MessagingResponse()
    msg = resp.message()

    # Manejo de memoria en Redis
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
                respuesta += f"📅 {c.get('fecha', 'Fecha desconocida')} a las {c.get('hora_inicio', 'Hora desconocida')}\n"
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

# Iniciar aplicación Flask
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
