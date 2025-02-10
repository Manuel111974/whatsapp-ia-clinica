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

# 🔍 **Buscar el ID real del empleado "Gabriel Asistente IA" en Koibox**
def obtener_id_empleado():
    url = f"{KOIBOX_URL}/empleados/"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        empleados = response.json().get("results", [])
        for empleado in empleados:
            if empleado.get("text") == "Gabriel Asistente IA":
                return empleado.get("value")  # ID real del empleado
    print(f"❌ No se encontró el empleado 'Gabriel Asistente IA'.")
    return None

# 🔍 **Buscar el ID real del servicio en Koibox**
def obtener_id_servicio(nombre_servicio):
    url = f"{KOIBOX_URL}/servicios/"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        servicios = response.json().get("results", [])
        for servicio in servicios:
            if servicio.get("nombre") == nombre_servicio:
                return servicio.get("id")  # ID real del servicio
    print(f"❌ No se encontró el servicio '{nombre_servicio}'.")
    return None

# 🔍 **Buscar cliente en Koibox**
def buscar_cliente(telefono):
    url = f"{KOIBOX_URL}/clientes/"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        clientes_data = response.json()
        for cliente in clientes_data.get("results", []):
            if cliente.get("movil") == telefono:
                return cliente.get("id")
    print(f"❌ Cliente con teléfono {telefono} no encontrado.")
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
        return cliente_data.get("id")  # ID del cliente recién creado
    print(f"❌ Error creando cliente en Koibox: {response.text}")
    return None

# ⏰ **Función para calcular la hora de finalización**
def calcular_hora_fin(hora_inicio, duracion_horas):
    h, m = map(int, hora_inicio.split(":"))
    h += duracion_horas
    return f"{h:02d}:{m:02d}"

# 📆 **Crear cita en Koibox**
def crear_cita(cliente_id, fecha, hora, servicio_nombre):
    empleado_id = obtener_id_empleado()
    servicio_id = obtener_id_servicio(servicio_nombre)

    if not empleado_id:
        return False, "⚠️ No se encontró el empleado Gabriel en Koibox."
    
    if not servicio_id:
        return False, f"⚠️ No se encontró el servicio '{servicio_nombre}' en Koibox."

    datos_cita = {
        "titulo": "Cita Gabriel Asistente IA",
        "notas": "Cita agendada por Gabriel (IA)",
        "duration": "01:00",
        "fecha": fecha,  # ✅ Corregido el formato YYYY-MM-DD
        "hora_inicio": hora,
        "hora_fin": calcular_hora_fin(hora, 1),  # Duración de 1 hora
        "is_empleado_aleatorio": False,
        "is_notificada_por_sms": True,
        "is_notificada_por_email": True,
        "is_notificada_por_whatsapp": True,
        "origen": "c",
        "precio": 0,
        "precio_sin_descuento": 0,
        "descuento": 0,
        "is_cliente_en_centro": False,
        "user": empleado_id,  # ✅ Usando el ID real de Gabriel
        "created_by": empleado_id,
        "cliente": cliente_id,  # ✅ Usando el ID real del cliente
        "estado": 1,  # ✅ Estado correcto
        "servicios": [servicio_id]  # ✅ Usando el ID real del servicio
    }

    response = requests.post(f"{KOIBOX_URL}/agenda/", headers=HEADERS, json=datos_cita)

    if response.status_code == 201:
        return True, "✅ ¡Tu cita ha sido creada con éxito!"
    else:
        return False, f"⚠️ No se pudo agendar la cita: {response.text}"

# 📩 **Webhook para recibir mensajes de WhatsApp**
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    sender = request.values.get("From", "")

    # Inicializar respuesta de Twilio
    resp = MessagingResponse()
    msg = resp.message()
    respuesta = "No entendí tu mensaje. ¿Puedes reformularlo? 😊"

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
        respuesta = "¡Perfecto! ¿Qué día prefieres? 📅 (Ejemplo: '2025-02-14')"

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

        cliente_id = buscar_cliente(telefono) or crear_cliente(nombre, telefono)

        if cliente_id:
            exito, mensaje = crear_cita(cliente_id, fecha, hora, servicio)
            respuesta = mensaje
        else:
            respuesta = "No pude registrar tu cita. Intenta más tarde."

    msg.body(respuesta)
    return str(resp)

# 🚀 **Iniciar aplicación**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
