import os
import redis
import requests
import openai
from flask import Flask, request
from datetime import datetime, timedelta
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

# Función para formatear la fecha a YYYY-MM-DD
def formatear_fecha(fecha_texto):
    try:
        fecha_obj = datetime.strptime(fecha_texto, "%d/%m/%Y")
        return fecha_obj.strftime("%Y-%m-%d")
    except ValueError:
        return None

# Función para calcular la hora de fin (+1 hora por defecto)
def calcular_hora_fin(hora_inicio):
    try:
        hora_obj = datetime.strptime(hora_inicio, "%H:%M")
        hora_fin = hora_obj + timedelta(hours=1)  # Duración de 1 hora
        return hora_fin.strftime("%H:%M")
    except ValueError:
        return None

# Función para crear una cita en Koibox
def crear_cita(cliente_id, fecha, hora):
    hora_fin = calcular_hora_fin(hora)

    if not hora_fin:
        return False, "⚠️ Error en el formato de la hora."

    datos_cita = {
        "cliente": cliente_id,  # Solo el ID, no un dict
        "fecha": fecha,
        "hora_inicio": hora,
        "hora_fin": hora_fin,
        "servicios": [1],  # Asignar ID del servicio (ajústalo según Koibox)
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
        fecha_formateada = formatear_fecha(incoming_msg)
        if fecha_formateada:
            redis_client.set(sender + "_fecha", fecha_formateada, ex=600)
            redis_client.set(sender + "_estado", "esperando_hora", ex=600)
            respuesta = "Genial. ¿A qué hora te gustaría la cita? (Ejemplo: '16:00') ⏰"
        else:
            respuesta = "⚠️ El formato de la fecha no es válido. Escríbelo como 'DD/MM/YYYY'."

    elif estado_usuario == "esperando_hora":
        redis_client.set(sender + "_hora", incoming_msg, ex=600)
        
        # Obtener datos almacenados en Redis
        nombre = redis_client.get(sender + "_nombre")
        telefono = redis_client.get(sender + "_telefono")
        fecha = redis_client.get(sender + "_fecha")
        hora = redis_client.get(sender + "_hora")

        print(f"🔍 Datos obtenidos antes de enviar a Koibox: {nombre}, {telefono}, {fecha}, {hora}")  # DEBUG

        if nombre and telefono and fecha and hora:
            # Simulamos que el cliente ID es el teléfono (esto debe ajustarse según Koibox)
            cliente_id = telefono  
            
            exito, mensaje = crear_cita(cliente_id, fecha, hora)
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

    # RESPUESTAS RÁPIDAS
    elif "ubicación" in incoming_msg:
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
