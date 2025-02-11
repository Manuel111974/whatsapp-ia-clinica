import os
import redis
import requests
import openai
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# 📌 Configuración de Flask
app = Flask(__name__)

# 📌 Configuración de Redis para la memoria temporal
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# 📌 Configuración de Koibox API
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"

HEADERS = {
    "X-Koibox-Key": KOIBOX_API_KEY,
    "Content-Type": "application/json"
}

# 📌 ID del empleado "Gabriel Asistente IA" en Koibox (Asegúrate de reemplazarlo con el ID real)
GABRIEL_USER_ID = 23527  # ⚠️ REEMPLAZAR CON EL ID REAL

# 🔍 **Buscar cliente en Koibox**
def buscar_cliente(telefono):
    url = f"{KOIBOX_URL}/clientes/"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        try:
            clientes_data = response.json()
            if "results" in clientes_data and isinstance(clientes_data["results"], list):
                clientes = clientes_data["results"]
                for cliente in clientes:
                    if cliente.get("movil") == telefono:
                        return cliente.get("id")  # Devuelve el ID del cliente si lo encuentra
            else:
                print(f"⚠️ Estructura inesperada en la respuesta de Koibox: {clientes_data}")
                return None
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
        return response.json().get("id")  # Devuelve el ID del cliente recién creado
    else:
        print(f"❌ Error creando cliente en Koibox: {response.text}")
        return None

# 📆 **Crear cita en Koibox**
def crear_cita(cliente_id, fecha, hora, servicio_id):
    # ✅ Convertir fecha al formato correcto
    fecha_formateada = "-".join(reversed(fecha.split("/")))  # Convierte 'DD/MM/YYYY' a 'YYYY-MM-DD'

    datos_cita = {
        "titulo": "Cita de tratamiento",  # ✅ Se agregó un título obligatorio
        "fecha": fecha_formateada,
        "hora_inicio": hora,
        "hora_fin": calcular_hora_fin(hora, 1),  # Duración de 1 hora
        "notas": "Cita agendada por Gabriel (IA)",
        "user": GABRIEL_USER_ID,  # ✅ Ahora es un ID, no un diccionario
        "cliente": cliente_id,  # ✅ Ahora es un ID, no un diccionario
        "servicios": [servicio_id],  # ✅ Ahora es un ID en lista, no un diccionario
        "estado": 1  # ✅ Estado programado
    }

    response = requests.post(f"{KOIBOX_URL}/agenda/", headers=HEADERS, json=datos_cita)

    if response.status_code == 201:
        return True, "✅ ¡Tu cita ha sido creada con éxito!"
    else:
        print(f"❌ Error al agendar la cita: {response.text}")
        return False, f"⚠️ No se pudo agendar la cita: {response.text}"

# ⏰ **Función para calcular la hora de finalización**
def calcular_hora_fin(hora_inicio, duracion_horas):
    h, m = map(int, hora_inicio.split(":"))
    h += duracion_horas
    return f"{h:02d}:{m:02d}"

# 📩 **Webhook para recibir mensajes de WhatsApp**
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
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
