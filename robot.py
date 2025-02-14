import os
import requests
import redis
from flask import Flask, request, jsonify

app = Flask(__name__)

# Configuración de Redis
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", 6379)
REDIS_DB = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

# Configuración de Koibox
KOIBOX_API_URL = "https://api.koibox.cloud/api/clientes/"
KOIBOX_HEADERS = {
    "Authorization": f"Bearer {os.getenv('KOIBOX_API_TOKEN')}",
    "Content-Type": "application/json"
}


@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Maneja los mensajes de WhatsApp y procesa citas en Koibox.
    """
    try:
        # Obtener los datos correctamente desde Twilio
        data = request.form  # Twilio envía datos en x-www-form-urlencoded

        # Mostrar datos crudos para depuración
        print(f"📩 **Datos recibidos (form):** {data}")

        # Validar si 'From' está presente
        sender = data.get("From", "").replace("whatsapp:", "").strip()
        message_body = data.get("Body", "").strip()

        if not sender:
            print("⚠️ **Error:** No se recibió un número de teléfono válido.")
            return jsonify({"status": "error", "message": "Número de teléfono no recibido.", "data": data}), 400

        print(f"📩 **Mensaje recibido de {sender}:** {message_body}")

        return jsonify({"status": "success", "message": "Mensaje recibido correctamente."})

    except Exception as e:
        print(f"❌ **Error en webhook:** {str(e)}")
        return jsonify({"status": "error", "message": "Error interno del servidor."}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
