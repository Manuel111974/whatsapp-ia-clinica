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

# 📌 **Función para llamar a OpenAI y generar respuestas**
def consultar_openai(mensaje):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Eres Gabriel, el asistente de Sonrisas Hollywood. Responde de manera profesional y amable."},
                {"role": "user", "content": mensaje}
            ]
        )
        return response["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"⚠️ ERROR en OpenAI: {str(e)}")
        return "Lo siento, no pude procesar tu consulta en este momento. Inténtalo más tarde. 😊"

# 📩 **Webhook de WhatsApp**
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "").replace("whatsapp:", "")

    resp = MessagingResponse()
    msg = resp.message()

    estado_usuario = redis_client.get(sender + "_estado")
    nombre = redis_client.get(sender + "_nombre")
    telefono = redis_client.get(sender + "_telefono")
    fecha = redis_client.get(sender + "_fecha")
    hora = redis_client.get(sender + "_hora")
    servicio = redis_client.get(sender + "_servicio")

    # 📌 **Saludo y presentación**
    if incoming_msg in ["hola", "buenas", "qué tal", "hey"]:
        if nombre:
            msg.body(f"¡Hola de nuevo, {nombre}! 😊 ¿En qué puedo ayudarte hoy?")
        else:
            msg.body("¡Hola! 😊 Soy *Gabriel*, el asistente de *Sonrisas Hollywood*. ¿En qué puedo ayudarte?")
        return str(resp)

    # 📌 **Ubicación**
    if any(word in incoming_msg for word in ["dónde estáis", "ubicación", "cómo llegar"]):
        msg.body(f"{UBICACION_CLINICA}\n📌 *Google Maps*: {GOOGLE_MAPS_LINK}")
        return str(resp)

    # 📌 **Ofertas activas**
    if "oferta" in incoming_msg:
        msg.body(f"💰 *Consulta nuestras ofertas actuales aquí*: {OFERTAS_LINK} 📢")
        return str(resp)

    # 📌 **Consulta de cita existente**
    if "mi cita" in incoming_msg or "cuando tengo la cita" in incoming_msg:
        if fecha and hora and servicio:
            msg.body(f"📅 Tu próxima cita es el *{fecha}* a las *{hora}* para *{servicio}* 😊")
        else:
            msg.body("No encuentro ninguna cita registrada a tu nombre. ¿Quieres agendar una?")
        return str(resp)

    # 📌 **Reservar cita**
    if "cita" in incoming_msg or "reservar" in incoming_msg:
        if fecha and hora:
            msg.body(f"📅 Ya tienes una cita programada el *{fecha}* a las *{hora}*. Si necesitas modificarla, dime 'Cambiar cita'.")
        else:
            redis_client.set(sender + "_estado", "esperando_nombre", ex=600)
            msg.body("¡Genial! Primero dime tu nombre completo 😊.")
        return str(resp)

    if estado_usuario == "esperando_nombre":
        redis_client.set(sender + "_nombre", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_telefono", ex=600)
        msg.body(f"Gracias, {incoming_msg}. Ahora dime tu número de teléfono 📞.")
        return str(resp)

    if estado_usuario == "esperando_telefono":
        redis_client.set(sender + "_telefono", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_fecha", ex=600)
        msg.body("¡Perfecto! ¿Qué día prefieres? 📅 (Ejemplo: '2025-02-14')")
        return str(resp)

    if estado_usuario == "esperando_fecha":
        redis_client.set(sender + "_fecha", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_hora", ex=600)
        msg.body("Genial. ¿A qué hora te gustaría la cita? ⏰ (Ejemplo: '11:00')")
        return str(resp)

    if estado_usuario == "esperando_hora":
        redis_client.set(sender + "_hora", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_servicio", ex=600)
        msg.body("¿Qué tratamiento necesitas? (Ejemplo: 'Botox', 'Diseño de sonrisa') 💉.")
        return str(resp)

    if estado_usuario == "esperando_servicio":
        redis_client.set(sender + "_servicio", incoming_msg, ex=600)

        cliente_id = buscar_cliente(telefono) or crear_cliente(nombre, telefono)
        notas = f"Solicitud de cita para {servicio}. Fecha: {fecha} - Hora: {hora}."

        if cliente_id:
            actualizar_notas(cliente_id, notas)
            msg.body(f"✅ ¡Tu cita para {servicio} ha sido registrada el {fecha} a las {hora}! 😊")
        else:
            msg.body("⚠️ No se pudo completar la cita. Por favor, intenta nuevamente.")

        return str(resp)

    # 📌 **Confirmación de citas 24h antes**
    hoy = datetime.now().strftime("%Y-%m-%d")
    fecha_recordatorio = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    if fecha == fecha_recordatorio:
        msg.body(f"📅 *Recordatorio de cita:* Mañana tienes cita a las *{hora}* para *{servicio}*.\n"
                 "¿Confirmas tu asistencia? Responde *Sí* o *No*.")

    # 📌 **Uso de OpenAI para responder cualquier otra consulta**
    respuesta_ia = consultar_openai(incoming_msg)
    msg.body(respuesta_ia)
    return str(resp)

# 🚀 **Lanzar la aplicación en Render**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)), debug=True)
