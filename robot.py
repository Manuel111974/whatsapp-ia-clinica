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

# Configuración de OpenAI (GPT-4-Turbo)
openai.api_key = os.getenv("OPENAI_API_KEY")

# Configuración de Twilio
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = "whatsapp:+14155238886"
MANUEL_WHATSAPP_NUMBER = "whatsapp:+34684472593"

# Configuración de Koibox
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"

HEADERS = {
    "X-Koibox-Key": KOIBOX_API_KEY,
    "Content-Type": "application/json"
}

# 🔥 **Función para generar respuestas con OpenAI**
def generar_respuesta(mensaje_usuario, historial):
    prompt = f"""
    Eres Gabriel, el asistente virtual de Sonrisas Hollywood. Responde de manera educada y profesional,
    ofreciendo información clara sobre tratamientos odontológicos y estéticos.

    Contexto de conversación previa:
    {historial}

    Usuario: {mensaje_usuario}
    Gabriel:
    """
    try:
        respuesta_openai = openai.ChatCompletion.create(
            model="gpt-4-turbo",
            messages=[{"role": "system", "content": prompt}],
            max_tokens=200,
            temperature=0.7
        )
        return respuesta_openai["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"Error con OpenAI: {e}")
        return "Lo siento, hubo un problema al generar la respuesta. ¿Puedes repetir tu consulta?"

# 🔍 **Función para buscar un cliente en Koibox**
def buscar_cliente(telefono):
    url = f"{KOIBOX_URL}/clientes/"
    response = requests.get(url, headers=HEADERS, params={"movil": telefono})

    if response.status_code == 200:
        clientes = response.json()
        if isinstance(clientes, list) and len(clientes) > 0:
            return clientes[0]["id_cliente"]
        else:
            print("⚠️ Cliente no encontrado en Koibox.")
            return None
    else:
        print(f"❌ Error buscando cliente en Koibox: {response.status_code} - {response.text}")
        return None

# 🔍 **Función para crear un cliente en Koibox**
def crear_cliente(nombre, telefono):
    datos_cliente = {
        "nombre": nombre,
        "movil": telefono
    }
    response = requests.post(f"{KOIBOX_URL}/clientes/", headers=HEADERS, json=datos_cliente)

    if response.status_code == 201:
        return response.json().get("id_cliente")
    else:
        print(f"❌ Error creando cliente en Koibox: {response.text}")
        return None

# 🔍 **Función para crear una cita en Koibox**
def crear_cita(cliente_id, fecha, hora):
    datos_cita = {
        "cliente": cliente_id,
        "fecha": fecha,
        "hora_inicio": hora,
        "hora_fin": str(int(hora[:2]) + 1) + ":00",
        "user": "Gabriel Asistente IA",
        "servicios": [1],  # ID del servicio "Primera Visita"
        "notas": "Cita agendada por Gabriel (IA)"
    }
    response = requests.post(f"{KOIBOX_URL}/agenda/", headers=HEADERS, json=datos_cita)

    if response.status_code == 201:
        return True, "✅ ¡Tu cita ha sido creada con éxito! Te esperamos en la clínica."
    else:
        print(f"❌ Error creando cita en Koibox: {response.text}")
        return False, f"⚠️ No se pudo agendar la cita: {response.text}"

# 🔥 **Función para enviar WhatsApp a Manuel cuando alguien pide cita**
def enviar_notificacion_whatsapp(nombre, telefono, fecha, hora, servicio):
    mensaje = (f"📢 *Nueva solicitud de cita*\n"
               f"👤 *Nombre:* {nombre}\n"
               f"📞 *Teléfono:* {telefono}\n"
               f"📅 *Fecha:* {fecha}\n"
               f"⏰ *Hora:* {hora}\n"
               f"💉 *Servicio:* {servicio}")

    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
    data = {
        "From": TWILIO_WHATSAPP_NUMBER,
        "To": MANUEL_WHATSAPP_NUMBER,
        "Body": mensaje
    }
    auth = (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    response = requests.post(url, data=data, auth=auth)

    return response.status_code == 201

# **Webhook para recibir mensajes de WhatsApp**
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    sender = request.values.get("From", "")

    resp = MessagingResponse()
    msg = resp.message()
    respuesta = "No entendí tu mensaje. ¿Puedes reformularlo? 😊"

    historial = redis_client.get(sender) or ""

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
        respuesta = "¿Qué día prefieres? 📅"

    elif redis_client.get(sender + "_estado") == "esperando_fecha":
        redis_client.set(sender + "_fecha", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_hora", ex=600)
        respuesta = "¿A qué hora te gustaría la cita? ⏰"

    elif redis_client.get(sender + "_estado") == "esperando_hora":
        redis_client.set(sender + "_hora", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_servicio", ex=600)
        respuesta = "¿Qué tratamiento necesitas? (Ejemplo: 'Botox', 'Diseño de sonrisa') 💉."

    elif redis_client.get(sender + "_estado") == "esperando_servicio":
        redis_client.set(sender + "_servicio", incoming_msg, ex=600)
        nombre, telefono, fecha, hora, servicio = [redis_client.get(sender + f"_{key}") for key in ["nombre", "telefono", "fecha", "hora", "servicio"]]

        cliente_id = buscar_cliente(telefono) or crear_cliente(nombre, telefono)
        if cliente_id:
            crear_cita(cliente_id, fecha, hora)
            enviar_notificacion_whatsapp(nombre, telefono, fecha, hora, servicio)
            respuesta = "✅ ¡Gracias! Tu cita ha sido registrada."

    msg.body(respuesta)
    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
