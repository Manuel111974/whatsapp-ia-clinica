import os
import requests
import redis
from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

# 🔹 Configuración de Redis
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", 6379)
REDIS_DB = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

# 🔹 Configuración de Koibox
KOIBOX_API_URL = "https://api.koibox.cloud/api/clientes/"
KOIBOX_HEADERS = {
    "Authorization": f"Bearer {os.getenv('KOIBOX_API_TOKEN')}",
    "Content-Type": "application/json"
}

# 🔹 Configuración de Twilio
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+34679846193")


def buscar_cliente(telefono):
    """
    Busca un cliente en Koibox por su número de teléfono.
    Si lo encuentra, devuelve su ID y sus notas.
    """
    try:
        print(f"🔍 Buscando cliente en Koibox con teléfono: {telefono}")
        response = requests.get(f"{KOIBOX_API_URL}?movil={telefono}", headers=KOIBOX_HEADERS)
        
        if response.status_code == 200:
            clientes = response.json()
            if clientes and len(clientes) > 0:
                cliente = clientes[0]
                print(f"✅ Cliente encontrado en Koibox: {cliente['id']}")
                return cliente["id"], cliente.get("notas", "")
            else:
                print(f"⚠️ Cliente no encontrado en Koibox: {telefono}")
        
        print(f"❌ Error en la búsqueda de cliente. Respuesta de Koibox: {response.text}")
        return None, None
    
    except Exception as e:
        print(f"🚨 Error en buscar_cliente(): {str(e)}")
        return None, None


def crear_cliente(telefono):
    """
    Crea un nuevo cliente en Koibox con el número de teléfono.
    """
    try:
        print(f"🆕 Creando nuevo cliente en Koibox: {telefono}")
        payload = {
            "nombre": "Cliente WhatsApp",
            "movil": telefono,
            "notas": "Cliente registrado por Gabriel IA.",
            "is_active": True,
            "is_anonymous": False
        }
        
        response = requests.post(KOIBOX_API_URL, json=payload, headers=KOIBOX_HEADERS)
        
        if response.status_code == 201:
            cliente = response.json()
            print(f"✅ Cliente creado correctamente en Koibox: {cliente['id']}")
            return cliente["id"]
        
        print(f"❌ Error creando cliente en Koibox. Respuesta: {response.text}")
        return None
    
    except Exception as e:
        print(f"🚨 Error en crear_cliente(): {str(e)}")
        return None


def guardar_cita_en_notas(cliente_id, mensaje):
    """
    Guarda los detalles de la cita en las notas del cliente en Koibox.
    """
    try:
        response = requests.get(f"{KOIBOX_API_URL}{cliente_id}/", headers=KOIBOX_HEADERS)
        if response.status_code == 200:
            cliente = response.json()
            notas_anteriores = cliente.get("notas", "")

            nueva_nota = f"{datetime.now().strftime('%d/%m/%Y %H:%M')} - {mensaje}"
            notas_actualizadas = f"{notas_anteriores}\n{nueva_nota}".strip()

            payload = {"notas": notas_actualizadas}
            response_update = requests.patch(f"{KOIBOX_API_URL}{cliente_id}/", json=payload, headers=KOIBOX_HEADERS)
            
            if response_update.status_code == 200:
                print(f"✅ Notas actualizadas en Koibox para el cliente {cliente_id}")
            else:
                print(f"❌ Error actualizando notas en Koibox: {response_update.text}")

    except Exception as e:
        print(f"🚨 Error en guardar_cita_en_notas(): {str(e)}")


def enviar_mensaje_whatsapp(telefono, mensaje):
    """
    Envía un mensaje de WhatsApp al usuario utilizando Twilio.
    """
    try:
        twilio_url = f"https://api.twilio.com/2010-04-01/Accounts/{os.getenv('TWILIO_ACCOUNT_SID')}/Messages.json"
        payload = {
            "From": TWILIO_WHATSAPP_NUMBER,
            "To": f"whatsapp:{telefono}",
            "Body": mensaje
        }

        auth = (os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
        response = requests.post(twilio_url, data=payload, auth=auth)
        
        if response.status_code == 201:
            print(f"✅ Mensaje enviado a {telefono}")
        else:
            print(f"❌ Error enviando mensaje a {telefono}: {response.text}")

    except Exception as e:
        print(f"🚨 Error en enviar_mensaje_whatsapp(): {str(e)}")


@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Recibe y procesa mensajes de WhatsApp de Twilio.
    """
    try:
        data = request.form  # Capturar los datos correctamente

        sender = data.get("From", "").replace("whatsapp:", "").strip()
        message_body = data.get("Body", "").strip()

        if not sender:
            return jsonify({"status": "error", "message": "Número de teléfono no recibido."}), 400

        print(f"📩 **Mensaje recibido de {sender}:** {message_body}")

        # 🔍 Buscar cliente en Koibox
        cliente_id, notas_cliente = buscar_cliente(sender)

        if not cliente_id:
            cliente_id = crear_cliente(sender)

            if not cliente_id:
                return jsonify({"status": "error", "message": "Error creando cliente en Koibox."}), 500

        # 📌 Guardar mensaje en notas
        guardar_cita_en_notas(cliente_id, message_body)

        # ✅ Enviar respuesta al usuario
        mensaje_respuesta = f"Hola, he registrado tu mensaje en nuestro sistema: \"{message_body}\".\nSi necesitas asistencia, dime cómo puedo ayudarte."
        enviar_mensaje_whatsapp(sender, mensaje_respuesta)

        return jsonify({"status": "success", "message": "Mensaje procesado correctamente."})

    except Exception as e:
        print(f"❌ **Error en webhook:** {str(e)}")
        return jsonify({"status": "error", "message": "Error interno del servidor."}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
