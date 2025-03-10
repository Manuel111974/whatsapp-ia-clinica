import os
import redis
import requests
import openai
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from datetime import datetime, timedelta

# Configuración de Flask
app = Flask(__name__)

# Configuración de Redis (Memoria de Gabriel)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Configuración de Koibox API
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"
HEADERS = {
    "X-Koibox-Key": KOIBOX_API_KEY,
    "Content-Type": "application/json"
}

# Configuración de OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

# Datos de la clínica
UBICACION_CLINICA = "📍 Calle Colón 48, Valencia."
GOOGLE_MAPS_LINK = "https://g.co/kgs/U5uMgPg"
OFERTAS_LINK = "https://www.facebook.com/share/18e8U4AJTN/?mibextid=wwXIfr"

# 📌 **Funciones para interactuar con Koibox**
def buscar_cliente(telefono):
    try:
        response = requests.get(f"{KOIBOX_URL}/clientes?telefono={telefono}", headers=HEADERS)
        if response.status_code == 200 and response.json():
            return response.json().get("id")
    except Exception as e:
        print(f"⚠️ ERROR al buscar cliente en Koibox: {str(e)}")
    return None

def crear_cliente(nombre, telefono):
    try:
        data = {"nombre": nombre, "telefono": telefono}
        response = requests.post(f"{KOIBOX_URL}/clientes", headers=HEADERS, json=data)
        if response.status_code == 201:
            return response.json().get("id")
    except Exception as e:
        print(f"⚠️ ERROR al crear cliente en Koibox: {str(e)}")
    return None

def actualizar_notas(cliente_id, nombre, fecha, hora, servicio):
    try:
        notas = f"Paciente: {nombre}\nFecha de cita: {fecha}\nHora: {hora}\nMotivo: {servicio}"
        data = {"notas": notas}
        response = requests.put(f"{KOIBOX_URL}/clientes/{cliente_id}", headers=HEADERS, json=data)
        return response.status_code == 200
    except Exception as e:
        print(f"⚠️ ERROR al actualizar notas en Koibox: {str(e)}")
    return False

# 📩 **Webhook de WhatsApp**
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "").replace("whatsapp:", "")

    resp = MessagingResponse()
    msg = resp.message()

    # 📌 **Cargar datos del paciente en Redis con un solo acceso**
    paciente_key = f"paciente:{sender}"
    estado_usuario, nombre, telefono, fecha, hora, servicio = redis_client.mget(
        f"{paciente_key}:estado",
        f"{paciente_key}:nombre",
        f"{paciente_key}:telefono",
        f"{paciente_key}:fecha",
        f"{paciente_key}:hora",
        f"{paciente_key}:servicio"
    )

    # 📌 **Saludo y presentación**
    if incoming_msg in ["hola", "buenas", "qué tal", "hey"]:
        msg.body(f"¡Hola de nuevo, {nombre}! 😊 ¿En qué puedo ayudarte hoy?" if nombre else 
                 "¡Hola! 😊 Soy *Gabriel*, el asistente de *Sonrisas Hollywood*. ¿En qué puedo ayudarte?")
        return str(resp)

    # 📌 **Ubicación**
    if "ubicación" in incoming_msg or "cómo llegar" in incoming_msg:
        msg.body(f"{UBICACION_CLINICA}\n📌 *Google Maps*: {GOOGLE_MAPS_LINK}")
        return str(resp)

    # 📌 **Ofertas activas**
    if "oferta" in incoming_msg:
        msg.body(f"💰 *Consulta nuestras ofertas actuales aquí*: {OFERTAS_LINK} 📢")
        return str(resp)

    # 📌 **Reservar cita (flujo de conversación y registro en Koibox)**
    estados = {
        "esperando_nombre": ("nombre", "Gracias, {value}. Ahora dime tu número de teléfono 📞.", "esperando_telefono"),
        "esperando_telefono": ("telefono", "¡Perfecto! ¿Qué día prefieres? 📅 (Ejemplo: '2025-02-14')", "esperando_fecha"),
        "esperando_fecha": ("fecha", "Genial. ¿A qué hora te gustaría la cita? ⏰ (Ejemplo: '11:00')", "esperando_hora"),
        "esperando_hora": ("hora", "¿Qué tratamiento necesitas? (Ejemplo: 'Botox', 'Diseño de sonrisa') 💉.", "esperando_servicio"),
        "esperando_servicio": ("servicio", "✅ ¡Tu cita ha sido registrada! 📅 {fecha} ⏰ {hora} para {value}.", None),
    }

    if incoming_msg in ["cita", "reservar"]:
        redis_client.mset({f"{paciente_key}:estado": "esperando_nombre"})
        redis_client.expire(paciente_key, 600)
        msg.body("¡Genial! Primero dime tu nombre completo 😊.")
        return str(resp)

    if estado_usuario in estados:
        key, response_text, next_state = estados[estado_usuario]
        redis_client.mset({f"{paciente_key}:{key}": incoming_msg})
        if next_state:
            redis_client.mset({f"{paciente_key}:estado": next_state})
        redis_client.expire(paciente_key, 600)

        if estado_usuario == "esperando_servicio":
            cliente_id = buscar_cliente(telefono)

            if not cliente_id:  # Si el cliente no existe, lo crea
                cliente_id = crear_cliente(nombre, telefono)

            if cliente_id:
                actualizar_notas(cliente_id, nombre, fecha, hora, incoming_msg)
                msg.body(f"✅ ¡Tu cita ha sido registrada en Koibox! 📅 {fecha} ⏰ {hora} para *{incoming_msg}* 😊")
            else:
                msg.body("⚠️ No se pudo registrar al paciente en Koibox. Intenta de nuevo más tarde.")

        else:
            msg.body(response_text.format(value=incoming_msg, fecha=fecha, hora=hora))

        return str(resp)

    # 📌 **Uso de OpenAI para responder cualquier otra consulta**
    respuesta_ia = consultar_openai(incoming_msg)
    msg.body(respuesta_ia)
    return str(resp)

# 🚀 **Lanzar la aplicación en Render**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)), debug=True)
