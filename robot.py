import os
import redis
import requests
import openai
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# Configuración de Flask
app = Flask(__name__)

# Configuración de Redis para memoria temporal
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Configuración de OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

# Configuración de Koibox API
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"

HEADERS = {
    "X-Koibox-Key": KOIBOX_API_KEY,
    "Content-Type": "application/json"
}

# 🔍 **Función para buscar cliente en Koibox**
def buscar_cliente(telefono):
    telefono = "".join(filter(str.isdigit, telefono))[:16]  # Asegurar formato correcto
    try:
        response = requests.get(f"{KOIBOX_URL}/clientes/?movil={telefono}", headers=HEADERS)
        if response.status_code == 200:
            clientes = response.json()
            if clientes and isinstance(clientes, list) and len(clientes) > 0:
                return clientes[0]["id_cliente"]  # Retorna el primer cliente encontrado
        return None
    except Exception as e:
        print(f"Error buscando cliente en Koibox: {e}")
        return None

# 📝 **Función para crear cliente en Koibox**
def crear_cliente(nombre, telefono):
    telefono = "".join(filter(str.isdigit, telefono))[:16]  # Asegurar formato correcto
    datos_cliente = {
        "nombre": nombre,
        "movil": telefono
    }
    try:
        response = requests.post(f"{KOIBOX_URL}/clientes/", headers=HEADERS, json=datos_cliente)
        if response.status_code == 201:
            return response.json().get("id_cliente")
        else:
            print(f"❌ Error creando cliente en Koibox: {response.text}")
            return None
    except Exception as e:
        print(f"Error creando cliente en Koibox: {e}")
        return None

# 📅 **Función para agendar cita en Koibox**
def agendar_cita(cliente_id, fecha, hora, servicio_id=1):
    datos_cita = {
        "cliente": cliente_id,
        "fecha": fecha,
        "hora_inicio": hora,
        "hora_fin": f"{int(hora[:2]) + 1}:00",  # Calcula hora fin automáticamente
        "servicios": [servicio_id],
        "user": "Gabriel Asistente IA",  # Asigna a Gabriel
        "notas": "Cita agendada por Gabriel (IA)"
    }
    try:
        response = requests.post(f"{KOIBOX_URL}/agenda/", headers=HEADERS, json=datos_cita)
        if response.status_code == 201:
            return True
        else:
            print(f"❌ Error agendando cita en Koibox: {response.text}")
            return False
    except Exception as e:
        print(f"Error agendando cita en Koibox: {e}")
        return False

# **Webhook para recibir mensajes de WhatsApp**
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    sender = request.values.get("From", "")

    resp = MessagingResponse()
    msg = resp.message()
    respuesta = "No entendí tu mensaje. ¿Puedes reformularlo? 😊"

    # Obtener historial del usuario en Redis
    historial = redis_client.get(sender) or ""

    # **Flujo de agendamiento de citas**
    if "cita" in incoming_msg or "reservar" in incoming_msg:
        redis_client.set(sender + "_estado", "esperando_nombre", ex=600)
        respuesta = "¡Genial! Primero dime tu nombre completo 😊."

    elif redis_client.get(sender + "_estado") == "esperando_nombre":
        redis_client.set(sender + "_nombre", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_telefono", ex=600)
        respuesta = f"Gracias, {incoming_msg} 😊. Ahora dime tu número de teléfono 📞."

    elif redis_client.get(sender + "_estado") == "esperando_telefono":
        redis_client.set(sender + "_telefono", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_fecha", ex=600)
        respuesta = "¡Perfecto! ¿Qué día prefieres? 📅 (Ejemplo: '12/02/2025')"

    elif redis_client.get(sender + "_estado") == "esperando_fecha":
        redis_client.set(sender + "_fecha", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_hora", ex=600)
        respuesta = "Genial. ¿A qué hora te gustaría la cita? ⏰ (Ejemplo: '16:00')"

    elif redis_client.get(sender + "_estado") == "esperando_hora":
        redis_client.set(sender + "_hora", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_servicio", ex=600)
        respuesta = "¿Qué tratamiento necesitas? (Ejemplo: 'Botox', 'Diseño de sonrisa') 💉."

    elif redis_client.get(sender + "_estado") == "esperando_servicio":
        redis_client.set(sender + "_servicio", incoming_msg, ex=600)

        nombre = redis_client.get(sender + "_nombre")
        telefono = redis_client.get(sender + "_telefono")
        fecha = redis_client.get(sender + "_fecha")
        hora = redis_client.get(sender + "_hora")
        servicio = redis_client.get(sender + "_servicio")

        if nombre and telefono and fecha and hora and servicio:
            cliente_id = buscar_cliente(telefono)
            if not cliente_id:
                cliente_id = crear_cliente(nombre, telefono)

            if cliente_id:
                cita_creada = agendar_cita(cliente_id, fecha, hora)
                if cita_creada:
                    respuesta = "✅ ¡Tu cita ha sido agendada con éxito en Koibox! Te esperamos en la clínica."
                else:
                    respuesta = "❌ Hubo un error al registrar la cita en Koibox. Por favor, intenta de nuevo."
            else:
                respuesta = "❌ Hubo un problema al registrar tu información. ¿Podrías intentar de nuevo?"
        else:
            respuesta = "❌ Faltan datos. Volvamos a empezar. ¿Cuál es tu nombre? 😊"
            redis_client.set(sender + "_estado", "esperando_nombre", ex=600)

    else:
        respuesta = "No entendí tu mensaje. ¿Puedes reformularlo? 😊"

    msg.body(respuesta)
    redis_client.set(sender, historial + f"\nUsuario: {incoming_msg}\nGabriel: {respuesta}", ex=3600)

    return str(resp)

# **Ruta principal**
@app.route("/")
def home():
    return "✅ Gabriel está activo y funcionando correctamente."

# **Ejecutar aplicación Flask**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
