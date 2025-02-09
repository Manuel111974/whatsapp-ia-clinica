from flask import Flask, request, jsonify
import os
import redis
import logging

# Configuración de logging para ver lo que ocurre en los logs de Render
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# 📌 Conectar con Redis usando la URL de entorno en Render
redis_url = os.getenv("REDIS_URL")
if not redis_url:
    logging.error("⚠️ ERROR: REDIS_URL no está configurada en las variables de entorno.")
    exit(1)

try:
    redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
    redis_client.ping()  # Prueba de conexión
    logging.info("✅ Conexión exitosa a Redis.")
except redis.exceptions.ConnectionError:
    logging.error("❌ ERROR: No se pudo conectar a Redis.")
    exit(1)

@app.route('/')
def home():
    return "🚀 WhatsApp Bot activo y funcionando en Render."

@app.route('/webhook', methods=['POST'])
def webhook():
    """ Recibe mensajes de WhatsApp desde Twilio y los guarda en Redis """
    data = request.json
    if not data:
        logging.warning("⚠️ Petición vacía recibida en /webhook")
        return jsonify({"error": "No hay datos en la solicitud"}), 400

    sender = data.get('From', 'desconocido')
    message = data.get('Body', '').strip()

    logging.info(f"📩 Mensaje recibido de {sender}: {message}")

    # 📌 Guardar en Redis
    redis_client.set(sender, message)

    # 📌 Responder automáticamente
    respuesta = f"Hola, {sender}. Recibí tu mensaje: '{message}'"
    return jsonify({"status": "ok", "reply": respuesta}), 200

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8080)
