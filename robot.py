import os
import redis
import requests
import json
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

# ID del asistente en Koibox
GABRIEL_USER_ID = 1  # ⚠️ REEMPLAZAR CON EL ID REAL

# Diccionario de servicios en Koibox (⚠️ Reemplazar con los IDs reales)
SERVICIOS_DISPONIBLES = {
    "botox": 2,
    "diseño de sonrisa": 3,
    "ortodoncia": 4
}

# 🔍 **Buscar cliente en Koibox**
def buscar_cliente(telefono):
    url = f"{KOIBOX_URL}/clientes/?movil={telefono}"  # Filtro por teléfono
    try:
        response = requests.get(url, headers=HEADERS, timeout=5)
        response.raise_for_status()  # Levanta un error si el código no es 200

        clientes_data = response.json()
        print(f"📩 [DEBUG] Respuesta de Koibox buscar_cliente: {json.dumps(clientes_data, indent=2)}")

        if clientes_data.get("results"):
            cliente = clientes_data["results"][0]  # Tomamos el primer resultado
            return cliente["id"]  # Devuelve el ID del cliente si lo encuentra

        return None  # No se encontró el cliente

    except requests.exceptions.RequestException as e:
        print(f"❌ [ERROR] buscar_cliente - {e}")
        return None

# 🆕 **Crear cliente en Koibox**
def crear_cliente(nombre, telefono):
    datos_cliente = {
        "nombre": nombre,
        "movil": telefono,
        "is_anonymous": False
    }

    try:
        response = requests.post(f"{KOIBOX_URL}/clientes/", headers=HEADERS, json=datos_cliente, timeout=5)
        response.raise_for_status()

        cliente_data = response.json()
        print(f"✅ [DEBUG] Cliente creado en Koibox: {json.dumps(cliente_data, indent=2)}")

        return cliente_data.get("id")  # Devuelve el ID del cliente recién creado

    except requests.exceptions.RequestException as e:
        print(f"❌ [ERROR] crear_cliente - {e}")
        return None

# 📆 **Crear cita en Koibox**
def crear_cita(cliente_id, fecha, hora, servicio_id):
    datos_cita = {
        "titulo": "Cita Gabriel Asistente IA",
        "notas": "Cita agendada por Gabriel (IA)",
        "duration": "01:00",
        "fecha": fecha,
        "hora_inicio": hora,
        "hora_fin": "00:00",  # Se recalculará automáticamente
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

    try:
        response = requests.post(f"{KOIBOX_URL}/agenda/", headers=HEADERS, json=datos_cita, timeout=5)
        response.raise_for_status()

        print(f"✅ [DEBUG] Cita creada en Koibox: {json.dumps(response.json(), indent=2)}")
        return True, "✅ ¡Tu cita ha sido creada con éxito!"

    except requests.exceptions.RequestException as e:
        print(f"❌ [ERROR] crear_cita - {e}")
        return False, "⚠️ No se pudo agendar la cita. Intenta más tarde."

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
        servicio_id = SERVICIOS_DISPONIBLES.get(incoming_msg, None)

        cliente_id = buscar_cliente(telefono) or crear_cliente(nombre, telefono)

        if cliente_id and servicio_id:
            _, mensaje = crear_cita(cliente_id, fecha, hora, servicio_id)
            respuesta = mensaje
        else:
            respuesta = "❌ Error: No se pudo crear la cita."

    msg.body(respuesta)
    return str(resp)

# 🚀 **Iniciar aplicación**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
