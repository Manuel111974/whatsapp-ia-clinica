import os
import redis
from flask import Flask, request, jsonify

app = Flask(__name__)

# Cargar Redis desde las variables de entorno
REDIS_URL = os.getenv("REDIS_URL")
if not REDIS_URL:
    raise ValueError("❌ ERROR: La variable REDIS_URL no está configurada.")

# Conectar con Redis
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)

@app.route("/", methods=["GET"])
def home():
    return "🤖 Gabriel, el asistente de Sonrisas Hollywood, está funcionando."

@app.route("/webhook", methods=["POST"])
def webhook():
    """ Endpoint para recibir mensajes de Twilio """
    try:
        data = request.form  # Twilio envía datos en formato `form-data`
        message_body = data.get("Body", "").strip()
        sender = data.get("From", "")
        
        # Guardar mensaje en Redis
        redis_client.set(f"msg:{sender}", message_body)
        
        response = f"📩 Recibido: {message_body}"
        return jsonify({"message": response}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
