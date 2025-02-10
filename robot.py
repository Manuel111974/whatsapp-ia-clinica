import os
import redis
import requests
import openai
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# Configuración de Flask
app = Flask(__name__)

# Configuración de Redis
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

# Función para obtener disponibilidad de citas en Koibox
def obtener_disponibilidad():
    try:
        response = requests.get(f"{KOIBOX_URL}/agenda/", headers=HEADERS)
        if response.status_code == 200:
            citas = response.json()
            if isinstance(citas, list) and len(citas) > 0:
                return citas[:5]  
            else:
                return None
        else:
            print(f"Error en Koibox: {response.text}")
            return None
    except Exception as e:
        print(f"Error en Koibox: {e}")
        return None

# Función para crear una cita en Koibox
def crear_cita(nombre, telefono, fecha, hora, servicio_id=1):
    datos_cita = {
        "cliente": {
            "nombre": nombre,
            "movil": telefono
        },
        "fecha": fecha,
        "hora_inicio": hora,
        "servicios": [{"id": servicio_id}],
        "notas": "Cita agendada por Gabriel (IA)"
    }
    print(f"📩 Enviando datos a Koibox: {datos_cita}")  # DEBUG

    try:
        response = requests.post(f"{KOIBOX_URL}/agenda/", headers=HEADERS, json=datos_cita)
        print(f"📩 Respuesta de Koibox: {response.status_code} - {response.text}")  # DEBUG

        if response.status_code == 201:
            return True, "✅ ¡Tu cita ha sido creada con éxito! Te esperamos en la clínica."
        else:
            return False, f"⚠️ No se pudo agendar la cita: {response.text}"
    except Exception as e:
        print(f"Error en Koibox: {e}")
        return False, f"Error en Koibox: {e}"

# Webhook para recibir mensajes de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    sender = request.values.get("From", "")

    # Inicializar respuesta de Twilio
    resp = MessagingResponse()
    msg = resp.message()

    # Obtener historial del usuario en Redis
    estado_usuario = redis_client.get(sender + "_estado") or ""

    # FLUJO DE CITAS PASO A PASO
    if estado_usuario == "esperando_nombre":
        redis_client.set(sender + "_nombre", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_telefono", ex=600)
        respuesta = f"Gracias, {incoming_msg} 😊. Ahora dime tu número de teléfono 📞."

    elif estado_usuario == "esperando_telefono":
        redis_client.set(sender + "_telefono", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_fecha", ex=600)
        respuesta = "¡Perfecto! Ahora dime qué fecha prefieres para la cita (Ejemplo: '12/02/2025') 📅."

    elif estado_usuario == "esperando_fecha":
        redis_client.set(sender + "_fecha", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_hora", ex=600)
        respuesta = "Genial. ¿A qué hora te gustaría la cita? (Ejemplo: '16:00') ⏰"

    elif estado_usuario == "esperando_hora":
        redis_client.set(sender + "_hora", incoming_msg, ex=600)
        
        # Obtener datos almacenados en Redis
        nombre = redis_client.get(sender + "_nombre")
        telefono = redis_client.get(sender + "_telefono")
        fecha = redis_client.get(sender + "_fecha")
        hora = redis_client.get(sender + "_hora")

        print(f"🔍 Datos obtenidos antes de enviar a Koibox: {nombre}, {telefono}, {fecha}, {hora}")  # DEBUG

        if nombre and telefono and fecha and hora:
            exito, mensaje = crear_cita(nombre, telefono, fecha, hora, servicio_id=1)
            respuesta = mensaje

            # Limpiar Redis
            redis_client.delete(sender + "_estado")
            redis_client.delete(sender + "_nombre")
            redis_client.delete(sender + "_telefono")
            redis_client.delete(sender + "_fecha")
            redis_client.delete(sender + "_hora")
        else:
            respuesta = "❌ Hubo un error con los datos. Vamos a intentarlo de nuevo. ¿Cómo te llamas? 😊"
            redis_client.set(sender + "_estado", "esperando_nombre", ex=600)

    # INICIO DEL FLUJO DE CITAS
    elif "cita" in incoming_msg or "quiero reservar" in incoming_msg:
        redis_client.set(sender + "_estado", "esperando_nombre", ex=600)
        respuesta = "¡Genial! Primero dime tu nombre completo 😊."

    # RESPUESTAS RÁPIDAS Y OPENAI PARA CONSULTAS GENERALES
    elif "precio" in incoming_msg or "coste" in incoming_msg:
        respuesta = "El diseño de sonrisa en composite tiene un precio medio de 2500€. ¿Quieres que te agende una cita de valoración gratuita? 😊"

    elif "botox" in incoming_msg:
        respuesta = "El tratamiento con Botox Vistabel está a 7€/unidad 💉. ¿Quieres reservar una consulta gratuita? 😊"

    elif "ubicación" in incoming_msg or "dónde están" in incoming_msg:
        respuesta = "📍 Nuestra clínica está en Calle Colón 48, Valencia. ¡Te esperamos!"

    elif "gracias" in incoming_msg:
        respuesta = "¡De nada! 😊 Siempre aquí para ayudarte."

    else:
        respuesta = "No estoy seguro de haber entendido. ¿Puedes reformularlo? 😊"

    msg.body(respuesta)
    return str(resp)

# Ruta principal de salud del bot
@app.route("/")
def home():
    return "✅ Gabriel está activo y funcionando correctamente."

# Iniciar aplicación Flask con Gunicorn
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
