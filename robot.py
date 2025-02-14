import os
import requests
import json
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
        # Ver contenido crudo recibido
        raw_data = request.get_data(as_text=True)
        print(f"📩 **Datos crudos recibidos:** {raw_data}")

        # Intentar parsear como JSON
        try:
            data = json.loads(raw_data)
        except json.JSONDecodeError:
            print("⚠️ **Error:** No se pudo decodificar JSON.")
            return jsonify({"status": "error", "message": "No se recibió JSON válido."}), 400

        # Validar si la clave 'From' está presente
        if "From" not in data:
            print(f"⚠️ **Error:** No se encontró 'From' en los datos: {data}")
            return jsonify({"status": "error", "message": "Número de teléfono no recibido.", "data": data}), 400

        sender = data["From"].replace("whatsapp:", "")
        message_body = data.get("Body", "").strip().lower()

        print(f"📩 **Mensaje recibido de {sender}:** {message_body}")

        return jsonify({"status": "success", "message": "Mensaje recibido correctamente."})

    except Exception as e:
        print(f"❌ **Error en webhook:** {str(e)}")
        return jsonify({"status": "error", "message": "Error interno del servidor."}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
