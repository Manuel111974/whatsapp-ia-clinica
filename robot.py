import os
import redis
import requests
import openai
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# Configuración de Flask
app = Flask(__name__)

# Configuración de Redis para la memoria temporal
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Configuración de Koibox API
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"

HEADERS = {
    "X-Koibox-Key": KOIBOX_API_KEY,
    "Content-Type": "application/json"
}

# ID del empleado "Gabriel Asistente IA" en Koibox
GABRIEL_USER_ID = 1  # ⚠️ REEMPLAZAR CON EL ID REAL

# Diccionario de servicios en Koibox (⚠️ Reemplazar con los IDs reales)
SERVICIOS_DISPONIBLES = {
    "botox": 2,  # ID del servicio de Botox
    "diseño de sonrisa": 3,  # ID del servicio de Diseño de Sonrisa
    "ortodoncia": 4
}

# 🔍 **Buscar cliente en Koibox**
def buscar_cliente(telefono):
    url = f"{KOIBOX_URL}/clientes/"
    while url:
        response = requests.get(url, headers=HEADERS)
        if response.status_code == 200:
            clientes_data = response.json()
            for cliente in clientes_data.get("results", []):
                if cliente.get("movil") == telefono:
                    return cliente.get("id")  # Devuelve el ID del cliente si lo encuentra
            url = clientes_data.get("next")  # Paginación
        else:
            print(f"❌ Error al obtener clientes de Koibox: {response.text}")
            return None
    return None

# 🆕 **Crear cliente en Koibox si no existe**
def crear_cliente(nombre, telefono):
    datos_cliente = {
        "nombre": nombre,
        "movil": telefono,
        "is_anonymous": False
    }
    response = requests.post(f"{KOIBOX_URL}/clientes/", headers=HEADERS, json=datos_cliente)
    
    if response.status_code == 201:
        cliente_data = response.json()
        print(f"✅ Cliente creado en Koibox: {cliente_data}")
        return cliente_data.get("id")  # Devuelve el ID del cliente recién creado
    else:
        print(f"❌ Error creando cliente en Koibox: {response.text}")
        return None

# ⏰ **Función para calcular la hora de finalización**
def calcular_hora_fin(hora_inicio, duracion_horas):
    h, m = map(int, hora_inicio.split(":"))
    h += duracion_horas
    return f"{h:02d}:{m:02d}"

# 📆 **Crear cita en Koibox**
def crear_cita(cliente_id, fecha, hora, servicio_id):
    datos_cita = {
        "titulo": "Cita Gabriel Asistente IA",
        "notas": "Cita agendada por Gabriel (IA)",
        "duration": "01:00",
        "fecha": fecha,
        "hora_inicio": hora,
        "hora_fin": calcular_hora_fin(hora, 1),
        "is_empleado_aleatorio": False,
        "is_notificada_por_sms": True,
        "is_notificada_por_email": True,
        "is_notificada_por_whatsapp": True,
        "origen": "c",
        "precio": 0,
        "precio_sin_descuento": 0,
        "descuento": 0,
        "is_cliente_en_centro": False,
        "user": GABRIEL_USER_ID,
        "created_by": GABRIEL_USER_ID,
        "cliente": cliente_id,
        "estado": 1,
        "servicios": [servicio_id]
    }

    response = requests.post(f"{KOIBOX_URL}/agenda/", headers=HEADERS, json=datos_cita)

    if response.status_code == 201:
        print(f"✅ Cita creada con éxito: {response.json()}")
        return True, "✅ ¡Tu cita ha sido creada con éxito!"
    else:
        print(f"❌ Error creando cita en Koibox: {response.text}")
        return False, f"⚠️ No se pudo agendar la cita: {response.text}"

# 📩 **Webhook para recibir mensajes de WhatsApp**
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    # Inicializar respuesta de Twilio
    resp = MessagingResponse()
    msg = resp.message()
    respuesta = "No entendí tu mensaje. ¿Puedes reformularlo? 😊"

    estado_actual = redis_client.get(sender + "_estado")

    if "cita" in incoming_msg or "reservar" in incoming_msg:
        redis_client.set(sender + "_estado", "esperando_nombre", ex=600)
        respuesta = "¡Genial! Primero dime tu nombre completo 😊."

    elif estado_actual == "esperando_nombre":
        redis_client.set(sender + "_nombre", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_telefono", ex=600)
        respuesta = f"Gracias, {incoming_msg} 😊. Ahora dime tu número de teléfono 📞."

    elif estado_actual == "esperando_telefono":
        redis_client.set(sender + "_telefono", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_fecha", ex=600)
        respuesta = "¡Perfecto! ¿Qué día prefieres? 📅 (Ejemplo: '2025-02-12')"

    elif estado_actual == "esperando_fecha":
        redis_client.set(sender + "_fecha", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_hora", ex=600)
        respuesta = "Genial. ¿A qué hora te gustaría la cita? ⏰ (Ejemplo: '16:00')"

    elif estado_actual == "esperando_hora":
        redis_client.set(sender + "_hora", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_servicio", ex=600)
        respuesta = "¿Qué tratamiento necesitas? (Ejemplo: 'Botox', 'Diseño de sonrisa') 💉."

    elif estado_actual == "esperando_servicio":
        redis_client.set(sender + "_servicio", incoming_msg, ex=600)

        nombre = redis_client.get(sender + "_nombre")
        telefono = redis_client.get(sender + "_telefono")
        fecha = redis_client.get(sender + "_fecha")
        hora = redis_client.get(sender + "_hora")
        servicio = redis_client.get(sender + "_servicio")

        servicio_id = SERVICIOS_DISPONIBLES.get(servicio, None)
        if not servicio_id:
            respuesta = f"⚠️ Lo siento, pero no tengo registrado ese servicio. ¿Podrías intentar de nuevo?"
        else:
            cliente_id = buscar_cliente(telefono)
            if not cliente_id:
                cliente_id = crear_cliente(nombre, telefono)

            if cliente_id:
                exito, mensaje = crear_cita(cliente_id, fecha, hora, servicio_id)
                respuesta = mensaje
            else:
                respuesta = "No pude registrar tu cita. Intenta más tarde."

    msg.body(respuesta)
    return str(resp)

# 🚀 **Iniciar aplicación**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
