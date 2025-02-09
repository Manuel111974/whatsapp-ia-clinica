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

# ⚠️ **CAMBIA ESTOS VALORES SEGÚN TU CONFIGURACIÓN EN KOIBOX**
KOIBOX_USER_ID = 10  # ⚠️ ID numérico de Gabriel en Koibox
KOIBOX_SERVICIO_ID = 15  # ⚠️ ID real del servicio "Primera Visita"

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

# Función para buscar un cliente en Koibox por teléfono
def buscar_cliente(telefono):
    try:
        response = requests.get(f"{KOIBOX_URL}/clientes/?telefono={telefono}", headers=HEADERS)
        if response.status_code == 200:
            clientes = response.json()
            if clientes and len(clientes) > 0:
                return clientes[0]["id"]  # Devuelve el ID del cliente si existe
        return None
    except Exception as e:
        print(f"❌ Error buscando cliente en Koibox: {e}")
        return None

# Función para crear un cliente en Koibox
def crear_cliente(nombre, telefono):
    datos_cliente = {
        "nombre": nombre,
        "movil": telefono
    }
    try:
        response = requests.post(f"{KOIBOX_URL}/clientes/", headers=HEADERS, json=datos_cliente)
        if response.status_code == 201:
            return response.json()["id"]  # Devuelve el ID del cliente creado
        else:
            print(f"⚠️ No se pudo crear el cliente: {response.text}")
            return None
    except Exception as e:
        print(f"❌ Error creando cliente en Koibox: {e}")
        return None

# Función para crear una cita en Koibox
def crear_cita(cliente_id, fecha, hora, observaciones):
    hora_fin = calcular_hora_fin(hora)

    if not hora_fin:
        return False, "⚠️ Error en el formato de la hora."

    datos_cita = {
        "cliente": cliente_id,  
        "fecha": fecha,
        "hora_inicio": hora,
        "hora_fin": hora_fin,
        "servicios": [KOIBOX_SERVICIO_ID],  
        "user": KOIBOX_USER_ID,  
        "notas": f"Interesado en: {observaciones} - Cita agendada por Gabriel (IA)"
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
        print(f"❌ Error en Koibox: {e}")
        return False, f"Error en Koibox: {e}"

# Webhook para recibir mensajes de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    sender = request.values.get("From", "")

    # Inicializar respuesta predeterminada
    respuesta = "🤖 No entendí tu mensaje. ¿Podrías reformularlo?"

    # Inicializar respuesta de Twilio
    resp = MessagingResponse()
    msg = resp.message()

    # Obtener historial del usuario en Redis
    estado_usuario = redis_client.get(sender + "_estado") or ""

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
        redis_client.set(sender + "_estado", "esperando_observaciones", ex=600)
        respuesta = "Para personalizar mejor tu visita, dime qué tratamiento te interesa (Ejemplo: 'Botox, diseño de sonrisa, ortodoncia') 😊."

    elif estado_usuario == "esperando_observaciones":
        redis_client.set(sender + "_observaciones", incoming_msg, ex=600)

        nombre = redis_client.get(sender + "_nombre")
        telefono = redis_client.get(sender + "_telefono")
        fecha = redis_client.get(sender + "_fecha")
        hora = redis_client.get(sender + "_hora")
        observaciones = redis_client.get(sender + "_observaciones")

        cliente_id = buscar_cliente(telefono)
        if not cliente_id:
            cliente_id = crear_cliente(nombre, telefono)

        if cliente_id:
            exito, mensaje = crear_cita(cliente_id, fecha, hora, observaciones)
            respuesta = mensaje
        else:
            respuesta = "⚠️ No se pudo crear el cliente en Koibox."

    msg.body(respuesta)
    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
