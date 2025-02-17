import os
import redis
import requests
import openai
from datetime import datetime, timedelta
import time
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

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

# Configuración de Twilio
TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP = "whatsapp:+14155238886"  # Número de Twilio

# Datos de la clínica
UBICACION_CLINICA = "📍 Calle Colón 48, Valencia."
GOOGLE_MAPS_LINK = "https://g.co/kgs/U5uMgPg"
OFERTAS_LINK = "https://www.facebook.com/share/18e8U4AJTN/?mibextid=wwXIfr"

# Función para llamar a OpenAI
def consultar_openai(mensaje):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "system", "content": "Eres Gabriel, el asistente de Sonrisas Hollywood."},
                      {"role": "user", "content": mensaje}]
        )
        return response["choices"][0]["message"]["content"].strip()
    except Exception:
        return "Lo siento, no pude procesar tu consulta en este momento. 😊"

# 📩 Webhook de WhatsApp
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

    # 📌 Saludos
    if incoming_msg in ["hola", "buenas", "qué tal", "hey"]:
        if nombre:
            msg.body(f"¡Hola de nuevo, {nombre}! 😊 ¿En qué puedo ayudarte hoy?")
        else:
            msg.body("¡Hola! 😊 Soy *Gabriel*, el asistente de *Sonrisas Hollywood*. ¿En qué puedo ayudarte?")
        return str(resp)

    # 📌 Recordar cita previa
    if "mi cita" in incoming_msg or "cuando tengo la cita" in incoming_msg:
        cita_guardada = redis_client.get(sender + "_cita")
        if cita_guardada:
            cita_info = eval(cita_guardada)
            msg.body(f"📅 Tu próxima cita es el *{cita_info['fecha']}* a las *{cita_info['hora']}* para *{cita_info['servicio']}*. 😊")
        else:
            msg.body("No encuentro ninguna cita registrada a tu nombre. ¿Quieres agendar una?")
        return str(resp)

    # 📌 Registro de Citas
    if "cita" in incoming_msg or "reservar" in incoming_msg:
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

        # Guardamos la cita en Redis
        cita = {"nombre": nombre, "telefono": telefono, "fecha": fecha, "hora": hora, "servicio": servicio}
        redis_client.set(sender + "_cita", str(cita), ex=604800)  # Guardar por 7 días

        msg.body(f"✅ ¡Tu cita para {servicio} ha sido registrada el {fecha} a las {hora}! 😊")
        return str(resp)

    # 📌 Respuesta Inteligente con OpenAI
    respuesta_ia = consultar_openai(incoming_msg)
    msg.body(respuesta_ia)
    return str(resp)

# 📌 Función para enviar recordatorio 24h antes
def enviar_recordatorio():
    now = datetime.now()
    
    for key in redis_client.scan_iter("*_cita"):
        datos_cita = redis_client.get(key)
        if not datos_cita:
            continue
        
        cita_info = eval(datos_cita)
        fecha_cita = datetime.strptime(cita_info["fecha"] + " " + cita_info["hora"], "%Y-%m-%d %H:%M")
        
        if now + timedelta(hours=24) >= fecha_cita >= now:
            mensaje = f"📅 ¡Hola {cita_info['nombre']}! Te recordamos tu cita en Sonrisas Hollywood para {cita_info['servicio']} mañana a las {cita_info['hora']}. ¿Confirmas tu asistencia? 😊"
            numero_paciente = cita_info["telefono"]
            
            url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json"
            data = {
                "From": TWILIO_WHATSAPP,
                "To": f"whatsapp:{numero_paciente}",
                "Body": mensaje,
            }
            requests.post(url, data=data, auth=(TWILIO_SID, TWILIO_AUTH_TOKEN))

            print(f"✅ Recordatorio enviado a {numero_paciente} para {cita_info['fecha']} a las {cita_info['hora']}")

while True:
    enviar_recordatorio()
    time.sleep(3600)  # Revisa cada hora

# 🚀 Lanzar aplicación
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
