import os
import redis
import requests
import openai
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# 🔧 **Configuración de Flask**
app = Flask(__name__)

# 🛠️ **Configuración de Redis**
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# 🔑 **Configuración de Koibox API**
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"

HEADERS = {
    "X-Koibox-Key": KOIBOX_API_KEY,
    "Content-Type": "application/json"
}

# 📌 **ID del usuario "Gabriel Asistente IA" en Koibox**
GABRIEL_USER_ID = 1  # ⚠️ REEMPLAZAR CON EL ID REAL

# ✅ **Endpoint para comprobar que el servidor está activo**
@app.route("/")
def home():
    return "Gabriel está en línea 🚀"

# 🔍 **Buscar cliente en Koibox**
def buscar_cliente(telefono):
    url = f"{KOIBOX_URL}/clientes/"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        try:
            clientes_data = response.json()
            clientes = clientes_data.get("clientes", clientes_data)  # Soporte para ambas estructuras

            for cliente in clientes:
                if cliente.get("movil") == telefono:
                    return cliente.get("value")  # Devuelve el ID del cliente si lo encuentra
        except Exception as e:
            print(f"❌ Error procesando la respuesta de Koibox: {e}")
            return None
    else:
        print(f"❌ Error al obtener clientes de Koibox: {response.text}")
        return None

    return None  # Si no encuentra el cliente, retorna None

# 🆕 **Crear cliente en Koibox si no existe**
def crear_cliente(nombre, telefono):
    datos_cliente = {
        "nombre": nombre,
        "movil": telefono,
        "is_anonymous": False
    }
    response = requests.post(f"{KOIBOX_URL}/clientes/", headers=HEADERS, json=datos_cliente)
    
    if response.status_code == 201:
        return response.json().get("value")  # Devuelve el ID del cliente recién creado
    else:
        print(f"❌ Error creando cliente en Koibox: {response.text}")
        return None

# 📆 **Crear cita en Koibox**
def crear_cita(cliente_id, fecha, hora, servicio_id=1):
    datos_cita = {
        "fecha": fecha,
        "hora_inicio": hora,
        "hora_fin": calcular_hora_fin(hora, 1),  # Duración 1 hora
        "notas": "Cita agendada por Gabriel (IA)",
        "user": {"value": GABRIEL_USER_ID, "text": "Gabriel Asistente IA"},
        "cliente": {"value": cliente_id},
        "estado": {"value": 1, "text": "Programada"},
        "servicios": [{"value": servicio_id}]
    }
    
    print("\n📤 Intentando crear cita en Koibox...")
    print("🔹 Datos enviados:", datos_cita)

    response = requests.post(f"{KOIBOX_URL}/agenda/", headers=HEADERS, json=datos_cita)

    print("🔹 Respuesta de Koibox:", response.status_code, response.text)  # Log del error

    if response.status_code == 201:
        print("✅ Cita creada con éxito")
        return True, "✅ ¡Tu cita ha sido creada con éxito!"
    else:
        print("⚠️ Error al crear cita:", response.text)  # Registro de error en logs
        return False, f"⚠️ No se pudo agendar la cita. Error: {response.text}"

# ⏰ **Función para calcular la hora de finalización**
def calcular_hora_fin(hora_inicio, duracion_horas):
    h, m = map(int, hora_inicio.split(":"))
    h += duracion_horas
    return f"{h:02d}:{m:02d}"

# 📩 **Webhook para recibir mensajes de WhatsApp**
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    sender = request.values.get("From", "")

    # Inicializar respuesta de Twilio
    resp = MessagingResponse()
    msg = resp.message()
    respuesta = "No entendí tu mensaje. ¿Puedes reformularlo? 😊"

    # Obtener historial del usuario en Redis
    historial = redis_client.get(sender) or ""

    # **Flujo de citas**
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
        respuesta = "¡Perfecto! ¿Qué día prefieres? 📅 (Ejemplo: '12/02/2025')"

    elif redis_client.get(sender + "_estado") == "esperando_fecha":
        redis_client.set(sender + "_fecha", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_hora", ex=600)
        respuesta = "Genial. ¿A qué hora te gustaría la cita? ⏰ (Ejemplo: '16:00')"

    elif redis_client.get(sender + "_estado") == "esperando_hora":
        redis_client.set(sender + "_hora", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_servicio", ex=600)
        respuesta = "¿Qué tratamiento necesitas? (Ejemplo: 'Botox', 'Diseño de sonrisa') 💉."

    elif redis_client.get(sender + "_estado") == "esperando_servicio":
        redis_client.set(sender + "_servicio", incoming_msg, ex=600)

        # Recopilar datos
        nombre = redis_client.get(sender + "_nombre")
        telefono = redis_client.get(sender + "_telefono")
        fecha = redis_client.get(sender + "_fecha")
        hora = redis_client.get(sender + "_hora")
        servicio = redis_client.get(sender + "_servicio")

        # Buscar o crear cliente en Koibox
        cliente_id = buscar_cliente(telefono)
        if not cliente_id:
            cliente_id = crear_cliente(nombre, telefono)

        # Crear cita
        if cliente_id:
            exito, mensaje = crear_cita(cliente_id, fecha, hora, 1)  # ID del servicio
            respuesta = mensaje
        else:
            respuesta = "No pude registrar tu cita. Intenta más tarde."

    msg.body(respuesta)
    return str(resp)

# 🚀 **Iniciar aplicación**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
