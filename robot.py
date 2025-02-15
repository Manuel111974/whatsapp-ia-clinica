import os
import redis
import requests
import json
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from datetime import datetime
from rapidfuzz import process

# Configuración de Flask
app = Flask(__name__)

# Configuración de Redis para memoria a corto plazo
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Configuración de API Koibox
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"
HEADERS = {"X-Koibox-Key": KOIBOX_API_KEY, "Content-Type": "application/json"}

# ID de Gabriel en Koibox (debe ser actualizado según la clínica)
GABRIEL_USER_ID = 1  

# URL de ofertas en Facebook
OFERTAS_URL = "https://www.facebook.com/share/18e8U4AJTN/?mibextid=wwXIfr"

# 📌 **Normalización de teléfonos**
def normalizar_telefono(telefono):
    telefono = telefono.strip().replace(" ", "").replace("-", "")
    if not telefono.startswith("+34"):  
        telefono = "+34" + telefono
    return telefono

# 📌 **Buscar cliente en Koibox**
def buscar_cliente(telefono):
    telefono = normalizar_telefono(telefono)
    url = f"{KOIBOX_URL}/clientes/"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        clientes = response.json().get("results", [])
        for cliente in clientes:
            if normalizar_telefono(cliente.get("movil")) == telefono:
                return cliente.get("id")
    return None

# 📌 **Crear cliente en Koibox**
def crear_cliente(nombre, telefono):
    telefono = normalizar_telefono(telefono)
    datos_cliente = {
        "nombre": nombre,
        "movil": telefono,
        "is_active": True,
        "notas": "Registrado por Gabriel IA"
    }
    response = requests.post(f"{KOIBOX_URL}/clientes/", headers=HEADERS, json=datos_cliente)
    return response.json().get("id") if response.status_code == 201 else None

# 📌 **Obtener servicios de Koibox**
def obtener_servicios():
    url = f"{KOIBOX_URL}/servicios/"
    response = requests.get(url, headers=HEADERS)
    return {s["nombre"]: s["id"] for s in response.json().get("results", [])} if response.status_code == 200 else {}

# 📌 **Encontrar el servicio más parecido**
def encontrar_servicio(servicio_solicitado):
    servicios = obtener_servicios()
    mejor_match, score, _ = process.extractOne(servicio_solicitado, servicios.keys()) if servicios else (None, 0, None)
    return servicios.get(mejor_match) if score > 75 else None

# 📌 **Registrar cita en Koibox**
def registrar_cita(cliente_id, nombre, telefono, fecha, hora, servicio_solicitado):
    servicio_id = encontrar_servicio(servicio_solicitado)
    if not servicio_id:
        return False, "No encontré un servicio similar. Por favor, indícame el tratamiento de nuevo."

    datos_cita = {
        "fecha": fecha,
        "hora_inicio": hora,
        "hora_fin": calcular_hora_fin(hora, 1),
        "titulo": servicio_solicitado,
        "notas": f"Cita agendada por Gabriel IA - Servicio: {servicio_solicitado}",
        "user": {"value": GABRIEL_USER_ID, "text": "Gabriel Asistente IA"},
        "cliente": {"value": cliente_id, "text": nombre, "movil": telefono},
        "servicios": [{"value": servicio_id}],
        "estado": 1
    }
    
    response = requests.post(f"{KOIBOX_URL}/agenda/cita/", headers=HEADERS, json=datos_cita)
    return (True, "✅ Tu cita ha sido registrada.") if response.status_code == 201 else (False, response.text)

# 📌 **Calcular hora de fin de la cita**
def calcular_hora_fin(hora_inicio, duracion_horas):
    h, m = map(int, hora_inicio.split(":"))
    h += duracion_horas
    return f"{h:02d}:{m:02d}"

# 📩 **Webhook de WhatsApp**
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    resp = MessagingResponse()
    msg = resp.message()

    estado_usuario = redis_client.get(sender + "_estado")

    # 🔹 **Gestión de interacciones inteligentes**
    if "oferta" in incoming_msg:
        msg.body(f"💰 Puedes ver nuestras ofertas aquí: {OFERTAS_URL} 📢")
        return str(resp)

    if "cita" in incoming_msg or "reservar" in incoming_msg:
        redis_client.set(sender + "_estado", "esperando_nombre", ex=600)
        msg.body("¡Genial! Primero dime tu nombre completo 😊.")
        return str(resp)

    if estado_usuario == "esperando_nombre":
        redis_client.set(sender + "_nombre", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_telefono", ex=600)
        msg.body("Gracias. Ahora dime tu número de teléfono 📞.")
        return str(resp)

    if estado_usuario == "esperando_telefono":
        redis_client.set(sender + "_telefono", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_fecha", ex=600)
        msg.body("¿Qué día prefieres? 📅")
        return str(resp)

    if estado_usuario == "esperando_fecha":
        redis_client.set(sender + "_fecha", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_hora", ex=600)
        msg.body("¿A qué hora prefieres? ⏰")
        return str(resp)

    if estado_usuario == "esperando_hora":
        redis_client.set(sender + "_hora", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_servicio", ex=600)
        msg.body("¿Qué tratamiento necesitas? 💉")
        return str(resp)

    if estado_usuario == "esperando_servicio":
        redis_client.set(sender + "_servicio", incoming_msg, ex=600)
        nombre = redis_client.get(sender + "_nombre")
        telefono = redis_client.get(sender + "_telefono")
        fecha = redis_client.get(sender + "_fecha")
        hora = redis_client.get(sender + "_hora")
        servicio = redis_client.get(sender + "_servicio")

        cliente_id = buscar_cliente(telefono) or crear_cliente(nombre, telefono)
        exito, mensaje = registrar_cita(cliente_id, nombre, telefono, fecha, hora, servicio) if cliente_id else (False, "Error al registrar la cita.")

        msg.body(mensaje)
        return str(resp)

    msg.body("No entendí tu mensaje. ¿Podrías reformularlo? 😊")
    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
