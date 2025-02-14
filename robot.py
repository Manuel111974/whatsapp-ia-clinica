import os
import requests
import json
import redis
from flask import Flask, request, jsonify

# Configuración de Flask
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

# Configuración de Twilio
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")


def buscar_cliente(telefono):
    """
    Busca al cliente en Redis y Koibox.
    """
    if not telefono:
        print("⚠️ Número de teléfono vacío o inválido.")
        return None

    cliente_id = REDIS_DB.get(telefono)
    if cliente_id:
        print(f"✅ Cliente encontrado en cache: {cliente_id}")
        return cliente_id

    # Buscar en Koibox si no está en cache
    response = requests.get(KOIBOX_API_URL, headers=KOIBOX_HEADERS, params={"movil": telefono})
    
    if response.status_code == 200 and response.json():
        cliente_id = response.json()[0]["id"]
        REDIS_DB.set(telefono, cliente_id)
        print(f"✅ Cliente encontrado en Koibox y guardado en cache: {cliente_id}")
        return cliente_id
    else:
        print(f"⚠️ Cliente no encontrado en Koibox: {telefono}")
        return None


def crear_cliente_koibox(nombre, telefono):
    """
    Crea un nuevo cliente en Koibox si no existe.
    """
    if not telefono:
        print("⚠️ Error: Intento de crear un cliente con un número vacío o inválido.")
        return None

    payload = {
        "nombre": nombre or "Cliente WhatsApp",
        "movil": telefono,
        "notas": "Cliente registrado por Gabriel IA.",
        "is_active": True,
        "is_anonymous": False,
        "is_suscrito_newsletter": False,
        "is_suscrito_encuestas": False
    }

    response = requests.post(KOIBOX_API_URL, headers=KOIBOX_HEADERS, json=payload)

    if response.status_code == 201:
        cliente_id = response.json()["id"]
        REDIS_DB.set(telefono, cliente_id)
        print(f"✅ Cliente creado correctamente en Koibox: {cliente_id}")
        return cliente_id
    else:
        print(f"❌ Error creando cliente en Koibox: {response.text}")
        return None


def actualizar_notas_koibox(cliente_id, nueva_nota):
    """
    Actualiza las notas del cliente en Koibox con información de la cita.
    """
    if not cliente_id:
        print("⚠️ No se puede actualizar notas en Koibox: Cliente ID no válido.")
        return

    response = requests.get(f"{KOIBOX_API_URL}{cliente_id}/", headers=KOIBOX_HEADERS)
    
    if response.status_code == 200:
        cliente_data = response.json()
        notas_actuales = cliente_data.get("notas", "")

        # Concatenar nuevas notas
        notas_actualizadas = f"{notas_actuales}\n{nueva_nota}" if notas_actuales else nueva_nota

        update_payload = {"notas": notas_actualizadas}
        update_response = requests.put(f"{KOIBOX_API_URL}{cliente_id}/", headers=KOIBOX_HEADERS, json=update_payload)

        if update_response.status_code == 200:
            print(f"✅ Notas actualizadas correctamente en Koibox para el cliente {cliente_id}")
        else:
            print(f"❌ Error al actualizar notas en Koibox: {update_response.text}")
    else:
        print(f"❌ Error al obtener cliente en Koibox: {response.text}")


@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Maneja los mensajes de WhatsApp y procesa citas en Koibox.
    """
    data = request.json

    # Registrar datos recibidos para depuración
    print(f"📩 Datos recibidos: {json.dumps(data, indent=2)}")

    if not data or "From" not in data:
        print("⚠️ Error: No se recibió un número de teléfono válido en la solicitud.")
        return jsonify({
            "status": "error",
            "message": "Número de teléfono no recibido.",
            "data_recibida": data  # Enviar datos recibidos para depuración
        }), 400

    sender = data.get("From")
    if not sender:
        print("⚠️ Error: El campo 'From' está vacío o es inválido.")
        return jsonify({"status": "error", "message": "El número de teléfono no es válido."}), 400

    sender = sender.replace("whatsapp:", "")  # Extraer número sin prefijo de WhatsApp
    message_body = data.get("Body", "").strip().lower()

    print(f"📩 Mensaje recibido de {sender}: {message_body}")

    # Buscar cliente en Redis y Koibox
    cliente_id = buscar_cliente(sender)
    if not cliente_id:
        print("🆕 Creando nuevo cliente en Koibox...")
        cliente_id = crear_cliente_koibox("Cliente WhatsApp", sender)

    if cliente_id:
        # Si el mensaje contiene una solicitud de cita
        if "cita" in message_body or "reserva" in message_body:
            tratamiento = "No especificado"
            fecha = "No especificada"
            hora = "No especificada"
            comentarios = ""

            # Extraer información de la cita
            if "para" in message_body:
                partes = message_body.split("para")
                tratamiento = partes[1].strip()

            if "el" in message_body:
                partes = message_body.split("el")
                fecha = partes[1].strip().split(" ")[0]  # Primer elemento después de "el"

            if "a las" in message_body:
                partes = message_body.split("a las")
                hora = partes[1].strip().split(" ")[0]  # Primer elemento después de "a las"

            # Agregar la cita a Koibox
            nueva_nota = f"""
            📝 **Cita registrada**:
            📅 Fecha: {fecha}
            🕒 Hora: {hora}
            💆 Tratamiento: {tratamiento}
            🗒️ Comentarios: {comentarios if comentarios else 'Ninguno'}
            """
            actualizar_notas_koibox(cliente_id, nueva_nota)

            return jsonify({
                "status": "success",
                "message": f"✅ Cita registrada para {fecha} a las {hora} en Koibox."
            })

    return jsonify({"status": "error", "message": "No se pudo procesar el mensaje."})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
