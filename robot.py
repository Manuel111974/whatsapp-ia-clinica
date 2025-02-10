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

# Configuración de OpenAI con el nuevo modelo
openai.api_key = os.getenv("OPENAI_API_KEY")

# Configuración de Twilio
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = "whatsapp:+14155238886"
MANUEL_WHATSAPP_NUMBER = "whatsapp:+34684472593"

# Configuración de Koibox API
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"
HEADERS = {
    "X-Koibox-Key": KOIBOX_API_KEY,
    "Content-Type": "application/json"
}

# 🔥 **Personalización de Gabriel**
GABRIEL_PERSONALIDAD = """
Eres Gabriel, el asistente virtual de *Sonrisas Hollywood*, una clínica especializada en *diseño de sonrisas y odontología estética* en Valencia.
Solo hablas de *Sonrisas Hollywood*, aunque sabes que Albane Clinic comparte la ubicación.  
Responde de forma clara y profesional, pero siempre centrándote en *Sonrisas Hollywood*.
"""

# 🔹 **Función para generar respuestas con OpenAI**
def generar_respuesta(mensaje_usuario, historial):
    prompt = f"""
    {GABRIEL_PERSONALIDAD}
    Contexto de conversación previa:
    {historial}

    Usuario: {mensaje_usuario}
    Gabriel:
    """

    try:
        respuesta_openai = openai.ChatCompletion.create(
            model="gpt-4-turbo",
            messages=[{"role": "system", "content": prompt}],
            max_tokens=150,
            temperature=0.7
        )
        return respuesta_openai["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"Error con OpenAI: {e}")
        return "Lo siento, hubo un problema al generar la respuesta. ¿Puedes repetir tu consulta?"

# 🔹 **Función para buscar cliente en Koibox**
def buscar_cliente(telefono):
    url = f"{KOIBOX_URL}/clientes/"
    response = requests.get(url, headers=HEADERS, params={"movil": telefono})
    
    if response.status_code == 200:
        clientes = response.json()
        if clientes and len(clientes) > 0:
            return clientes[0]["id_cliente"]
    return None

# 🔹 **Función para crear un cliente en Koibox**
def crear_cliente(nombre, telefono):
    url = f"{KOIBOX_URL}/clientes/"
    datos_cliente = {"nombre": nombre, "movil": telefono}
    response = requests.post(url, headers=HEADERS, json=datos_cliente)
    
    if response.status_code == 201:
        return response.json().get("id_cliente")
    else:
        print(f"❌ Error creando cliente en Koibox: {response.text}")
        return None

# 🔹 **Función para enviar notificación de cita a Manuel**
def enviar_notificacion_whatsapp(nombre, telefono, fecha, hora, servicio):
    mensaje = (f"📢 *Nueva solicitud de cita en Sonrisas Hollywood*\n"
               f"👤 *Nombre:* {nombre}\n"
               f"📞 *Teléfono:* {telefono}\n"
               f"📅 *Fecha:* {fecha}\n"
               f"⏰ *Hora:* {hora}\n"
               f"💉 *Servicio:* {servicio}")

    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
    data = {"From": TWILIO_WHATSAPP_NUMBER, "To": MANUEL_WHATSAPP_NUMBER, "Body": mensaje}
    auth = (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    response = requests.post(url, data=data, auth=auth)

    return response.status_code == 201

# **📌 Webhook para recibir mensajes de WhatsApp**
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    # Inicializar respuesta de Twilio
    resp = MessagingResponse()
    msg = resp.message()

    estado_usuario = redis_client.get(sender + "_estado") or ""

    # **🗺️ Responder preguntas sobre la ubicación**
    if "dónde están" in incoming_msg or "ubicación" in incoming_msg:
        respuesta = "📍 *Sonrisas Hollywood* está en *Calle Colón 48, Valencia*. ¡Te esperamos para transformar tu sonrisa! 😁✨"

    # **📌 Preguntar si es paciente**
    elif "cita" in incoming_msg or "reservar" in incoming_msg:
        redis_client.set(sender + "_estado", "verificando_paciente", ex=600)
        respuesta = "¿Eres paciente de Sonrisas Hollywood? Responde 'Sí' o 'No'."

    # **🛠️ Si ya es paciente, buscarlo en Koibox**
    elif estado_usuario == "verificando_paciente":
        if "si" in incoming_msg:
            redis_client.set(sender + "_estado", "esperando_telefono_paciente", ex=600)
            respuesta = "¡Genial! ¿Cuál es tu número de teléfono registrado? 📞"
        else:
            redis_client.set(sender + "_estado", "esperando_nombre", ex=600)
            respuesta = "¡No hay problema! Primero dime tu nombre completo 😊."

    # **📌 Confirmar teléfono y buscar en Koibox**
    elif estado_usuario == "esperando_telefono_paciente":
        cliente_id = buscar_cliente(incoming_msg)
        if cliente_id:
            redis_client.set(sender + "_cliente_id", cliente_id, ex=600)
            redis_client.set(sender + "_estado", "esperando_fecha", ex=600)
            respuesta = "Perfecto. ¿Qué día prefieres para tu cita? 📅"
        else:
            respuesta = "❌ No encontramos tu número. ¿Puedes confirmarlo o escribir 'No' para registrarte?"

    # **📌 Si no es paciente, registrar datos**
    elif estado_usuario == "esperando_nombre":
        redis_client.set(sender + "_nombre", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_telefono", ex=600)
        respuesta = "Gracias 😊. Ahora dime tu número de teléfono 📞."

    elif estado_usuario == "esperando_telefono":
        redis_client.set(sender + "_telefono", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_fecha", ex=600)
        respuesta = "¡Perfecto! ¿Qué día prefieres? 📅"

    # **📌 Confirmar fecha, hora y servicio**
    elif estado_usuario == "esperando_fecha":
        redis_client.set(sender + "_fecha", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_hora", ex=600)
        respuesta = "Genial. ¿A qué hora te gustaría la cita? ⏰"

    elif estado_usuario == "esperando_hora":
        redis_client.set(sender + "_hora", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_servicio", ex=600)
        respuesta = "¿Qué tratamiento necesitas? 💉 (Ejemplo: 'Botox', 'Diseño de sonrisa')"

    else:
        respuesta = generar_respuesta(incoming_msg, "")

    msg.body(respuesta)
    return str(resp)

# **Ruta principal**
@app.route("/")
def home():
    return "✅ Gabriel está activo y funcionando correctamente."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
