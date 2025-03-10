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
    """Busca un cliente en Koibox por teléfono."""
    try:
        response = requests.get(f"{KOIBOX_URL}/clientes?telefono={telefono}", headers=HEADERS)
        if response.status_code == 200 and response.json():
            return response.json().get("id")
    except Exception as e:
        print(f"⚠️ ERROR al buscar cliente en Koibox: {str(e)}")
    return None

def crear_cliente(nombre, telefono):
    """Crea un nuevo cliente en Koibox."""
    try:
        data = {"nombre": nombre, "telefono": telefono}
        response = requests.post(f"{KOIBOX_URL}/clientes", headers=HEADERS, json=data)
        if response.status_code == 201:
            return response.json().get("id")
    except Exception as e:
        print(f"⚠️ ERROR al crear cliente en Koibox: {str(e)}")
    return None

def agendar_cita(cliente_id, fecha, hora, servicio):
    """Agenda una cita en Koibox."""
    try:
        data = {
            "cliente_id": cliente_id,
            "fecha": fecha,
            "hora": hora,
            "servicio": servicio
        }
        response = requests.post(f"{KOIBOX_URL}/citas", headers=HEADERS, json=data)
        return response.status_code == 201
    except Exception as e:
        print(f"⚠️ ERROR al agendar cita en Koibox: {str(e)}")
    return False

def actualizar_notas(cliente_id, nombre, fecha, hora, servicio):
    """Actualiza las notas en la ficha del paciente en Koibox."""
    try:
        notas = f"Paciente: {nombre}\nFecha de cita: {fecha}\nHora: {hora}\nMotivo: {servicio}"
        data = {"notas": notas}
        response = requests.put(f"{KOIBOX_URL}/clientes/{cliente_id}", headers=HEADERS, json=data)
        return response.status_code == 200
    except Exception as e:
        print(f"⚠️ ERROR al actualizar notas en Koibox: {str(e)}")
    return False

# 📌 **Función para llamar a OpenAI con historial de conversación**
def consultar_openai(mensaje, sender):
    historial_key = f"historial:{sender}"
    historial = redis_client.lrange(historial_key, 0, 4)  # Últimos 5 mensajes
    historial.append(f"Usuario: {mensaje}")

    contexto = [
        {"role": "system", "content": (
            "Eres *Gabriel*, el asistente virtual de *Sonrisas Hollywood*. "
            "Tu tono debe ser profesional, cercano y amable. "
            "Brindas información sobre odontología estética, medicina estética y los servicios de la clínica. "
            "Si la pregunta es sobre precios, derivar al enlace de ofertas. "
            "Si no sabes la respuesta, redirige al equipo de atención de la clínica."
        )}
    ]

    for msg in historial:
        contexto.append({"role": "user", "content": msg})

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=contexto
        )
        respuesta_ia = response["choices"][0]["message"]["content"].strip()
        redis_client.lpush(historial_key, f"Gabriel: {respuesta_ia}")
        redis_client.ltrim(historial_key, 0, 4)
        redis_client.expire(historial_key, 3600)
        return respuesta_ia
    except Exception as e:
        print(f"⚠️ ERROR en OpenAI: {str(e)}")
        return "Lo siento, no pude procesar tu consulta en este momento. Inténtalo más tarde. 😊"

# 📩 **Webhook de WhatsApp**
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    sender = request.values.get("From", "").replace("whatsapp:", "")

    resp = MessagingResponse()
    msg = resp.message()

    # 📌 **Casos especiales**
    if incoming_msg.lower() in ["hola", "buenas", "qué tal", "hey"]:
        msg.body("¡Hola! 😊 Soy *Gabriel*, el asistente virtual de *Sonrisas Hollywood*. ¿En qué puedo ayudarte?")
        return str(resp)

    if "ubicación" in incoming_msg.lower() or "cómo llegar" in incoming_msg.lower():
        msg.body(f"{UBICACION_CLINICA}\n📌 *Google Maps*: {GOOGLE_MAPS_LINK}")
        return str(resp)

    if "oferta" in incoming_msg.lower():
        msg.body(f"💰 *Consulta nuestras ofertas actuales aquí*: {OFERTAS_LINK} 📢")
        return str(resp)

    # 📌 **Reservar cita**
    paciente_key = f"paciente:{sender}"
    estado_usuario, nombre, telefono, fecha, hora, servicio = redis_client.mget(
        f"{paciente_key}:estado",
        f"{paciente_key}:nombre",
        f"{paciente_key}:telefono",
        f"{paciente_key}:fecha",
        f"{paciente_key}:hora",
        f"{paciente_key}:servicio"
    )

    if incoming_msg.lower() in ["cita", "reservar"]:
        redis_client.mset({f"{paciente_key}:estado": "esperando_nombre"})
        redis_client.expire(paciente_key, 600)
        msg.body("¡Genial! Primero dime tu nombre completo 😊.")
        return str(resp)

    if estado_usuario == "esperando_servicio":
        cliente_id = buscar_cliente(telefono) or crear_cliente(nombre, telefono)
        if cliente_id:
            if agendar_cita(cliente_id, fecha, hora, servicio):
                actualizar_notas(cliente_id, nombre, fecha, hora, incoming_msg)
                msg.body(f"✅ ¡Tu cita ha sido registrada en Koibox! 📅 {fecha} ⏰ {hora} para *{incoming_msg}* 😊")
            else:
                msg.body("⚠️ No se pudo registrar la cita en Koibox. Intenta de nuevo más tarde.")
        else:
            msg.body("⚠️ No se pudo registrar al paciente en Koibox. Intenta de nuevo más tarde.")

        return str(resp)

    # 📌 **Uso de OpenAI para responder cualquier otra consulta**
    respuesta_ia = consultar_openai(incoming_msg, sender)
    msg.body(respuesta_ia)
    return str(resp)

# 🚀 **Lanzar la aplicación en Render**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)), debug=True)
