import os
import redis
import requests
from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse

app = Flask(__name__)

# Configuración de Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Configuración de Koibox API
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"

# Función para crear una cita en Koibox
def crear_cita_koibox(nombre, email, movil, fecha, hora_inicio, hora_fin):
    headers = {
        "Authorization": f"Bearer {KOIBOX_API_KEY}",
        "Content-Type": "application/json"
    }
    
    datos_cita = {
        "notas": f"Cita programada para {nombre}",
        "duration": "01:00",
        "fecha": fecha,
        "hora_inicio": hora_inicio,
        "hora_fin": hora_fin,
        "is_notificada_por_sms": False,
        "is_notificada_por_email": False,
        "is_notificada_por_whatsapp": True,
        "user": {
            "value": 1,
            "text": "Gabriel"
        },
        "cliente": {
            "text": nombre,
            "value": 1001,  # Este ID debe ser dinámico según Koibox
            "email": email,
            "movil": movil
        },
        "servicios": [
            {
                "id": 10,  # ID del servicio en Koibox
                "value": 10,
                "text": "Consulta gratuita",
                "precio": 0
            }
        ]
    }

    response = requests.post(f"{KOIBOX_URL}/agenda/", json=datos_cita, headers=headers)
    
    if response.status_code == 200:
        return "✅ Cita registrada con éxito en Koibox."
    else:
        return f"⚠️ Error al crear cita: {response.json()}"

# Webhook de WhatsApp para Gabriel
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    resp = MessagingResponse()
    msg = resp.message()

    # Guardar historial en Redis
    historial = redis_client.get(sender) or ""
    historial += f"\nUsuario: {incoming_msg}"

    if "cita" in incoming_msg:
        # Datos de prueba, en un caso real deben pedirse al usuario
        nombre = "Juan Pérez"
        email = "juan@example.com"
        movil = "666777888"
        fecha = "2025-02-10"
        hora_inicio = "10:00"
        hora_fin = "11:00"

        respuesta = crear_cita_koibox(nombre, email, movil, fecha, hora_inicio, hora_fin)
    
    else:
        respuesta = "No entendí tu mensaje. ¿Podrías reformularlo? 😊"

    # Guardar respuesta en Redis
    historial += f"\nGabriel: {respuesta}"
    redis_client.set(sender, historial, ex=3600)

    msg.body(respuesta)
    return str(resp)

# Iniciar aplicación Flask
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
