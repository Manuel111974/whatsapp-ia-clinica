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

@app.route("/set_memory", methods=["POST"])
def set_memory():
    """ Guarda un valor en Redis. """
    try:
        data = request.json
        key = data.get("key")
        value = data.get("value")

        if not key or not value:
            return jsonify({"error": "Clave y valor requeridos"}), 400

        redis_client.set(key, value)
        return jsonify({"message": f"✅ Se guardó {key} en memoria"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/get_memory/<key>", methods=["GET"])
def get_memory(key):
    """ Recupera un valor de Redis. """
    try:
        value = redis_client.get(key)
        if value:
            return jsonify({"key": key, "value": value}), 200
        else:
            return jsonify({"error": "❌ Clave no encontrada"}), 404

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/delete_memory/<key>", methods=["DELETE"])
def delete_memory(key):
    """ Elimina un valor de Redis. """
    try:
        redis_client.delete(key)
        return jsonify({"message": f"✅ Se eliminó {key} de memoria"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Prueba de conexión a Redis al iniciar el servidor
try:
    print("🔄 Probando conexión a Redis...")
    print("PONG" if redis_client.ping() else "❌ No se pudo conectar")
    print("✅ Conexión exitosa a Redis")
except redis.exceptions.ConnectionError as e:
    print(f"❌ Error de conexión a Redis: {e}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
