import os
import redis
import requests
import openai
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# 📌 Configuración de Flask
app = Flask(__name__)

# 📌 Configuración de Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# 📌 Configuración de OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

# 📌 Configuración de Koibox API
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"

HEADERS = {
    "X-Koibox-Key": KOIBOX_API_KEY,
    "Content-Type": "application/json"
}

# 📌 ID del empleado "Gabriel Asistente IA" en Koibox
GABRIEL_USER_ID = 1  # ⚠️ REEMPLAZAR SI ES NECESARIO

# 📌 Función para normalizar teléfono
def normalizar_telefono(telefono):
    telefono = telefono.strip().replace(" ", "").replace("-", "")
    if not telefono.startswith("+34"):  
        telefono = "+34" + telefono
    return telefono

# 📌 Obtener disponibilidad de citas en Koibox
def obtener_disponibilidad():
    try:
        response = requests.get(f"{KOIBOX_URL}/agenda/", headers=HEADERS)
        if response.status_code == 200:
            citas = response.json()
            if isinstance(citas, list) and len(citas) > 0:
                return citas[:5]  # Devuelve las primeras 5 citas disponibles
            else:
                return None
        else:
            print(f"❌ Error en Koibox: {response.text}")
            return None
    except Exception as e:
        print(f"❌ Error en Koibox: {e}")
        return None

# 📌 Buscar cliente en Koibox
def buscar_cliente(telefono):
    telefono = normalizar_telefono(telefono)
    url = f"{KOIBOX_URL}/clientes/"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        clientes_data = response.json()
        if "results" in clientes_data and isinstance(clientes_data["results"], list):
            for cliente in clientes_data["results"]:
                if normalizar_telefono(cliente.get("movil", "")) == telefono:
                    return cliente.get("id")  # Devuelve el ID si se encuentra
        return None
    else:
        print(f"❌ Error al obtener clientes de Koibox: {response.text}")
        return None

# 📌 Crear cliente en Koibox si no existe
def crear_cliente(nombre, telefono):
    telefono = normalizar_telefono(telefono)
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

# 📌 Crear cita en Koibox
def crear_cita(cliente_id, nombre, telefono, fecha, hora, servicio):
    datos_cita = {
        "fecha": fecha,
        "hora_inicio": hora,
        "hora_fin": calcular_hora_fin(hora, 1),  
        "titulo": servicio,
        "notas": "Cita agendada por Gabriel (IA)",
        "user": {"value": GABRIEL_USER_ID, "text": "Gabriel Asistente IA"},
        "cliente": {"value": cliente_id, "text": nombre, "movil": telefono},
        "estado": {"id": 1, "nombre": "Pendiente"}
    }
    
    response = requests.post(f"{KOIBOX_URL}/agenda/cita", headers=HEADERS, json=datos_cita)
    
    if response.status_code == 201:
        return True, f"✅ ¡Tu cita para {servicio} ha sido creada con éxito el {fecha} a las {hora}! 🎉"
    else:
        return False, f"⚠️ Algo no ha salido bien. No pude agendar la cita: {response.text}"

# 📌 Calcular hora de finalización
def calcular_hora_fin(hora_inicio, duracion_horas):
    h, m = map(int, hora_inicio.split(":"))
    h += duracion_horas
    return f"{h:02d}:{m:02d}"

# 📌 Generar respuesta con OpenAI GPT-4
def generar_respuesta(contexto):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4-turbo",
            messages=[
                {"role": "system", "content": "Eres Gabriel, el asistente virtual de Sonrisas Hollywood, una clínica de odontología estética en Valencia. Responde de manera cálida, profesional y natural."},
                {"role": "user", "content": contexto}
            ],
            max_tokens=150
        )
        return response["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"❌ Error en OpenAI: {e}")
        return "Lo siento, no puedo responder en este momento."

# 📌 Webhook para recibir mensajes de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    resp = MessagingResponse()
    msg = resp.message()
    respuesta = "No entendí tu mensaje. ¿Puedes reformularlo? 😊"

    estado_usuario = redis_client.get(sender + "_estado") or ""

    if "cita" in incoming_msg or "reservar" in incoming_msg:
        redis_client.set(sender + "_estado", "esperando_nombre", ex=600)
        respuesta = "¡Genial! 😊 Para empezar, ¿podrías decirme tu nombre completo?"

    elif estado_usuario == "esperando_nombre":
        redis_client.set(sender + "_nombre", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_telefono", ex=600)
        respuesta = f"Gracias, {incoming_msg}! Ahora dime tu número de teléfono 📞 para registrar tu cita."

    elif estado_usuario == "esperando_telefono":
        redis_client.set(sender + "_telefono", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_fecha", ex=600)
        respuesta = "¡Perfecto! Ahora dime qué día prefieres 📅 (Ejemplo: '2025-02-12')."

    elif estado_usuario == "esperando_fecha":
        redis_client.set(sender + "_fecha", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_hora", ex=600)
        respuesta = "Genial. ¿A qué hora te gustaría la cita? ⏰ (Ejemplo: '16:00')."

    elif estado_usuario == "esperando_hora":
        redis_client.set(sender + "_hora", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_servicio", ex=600)
        respuesta = "¿Qué tratamiento necesitas? (Ejemplo: 'Botox', 'Diseño de sonrisa') 💉."

    elif estado_usuario == "esperando_servicio":
        nombre = redis_client.get(sender + "_nombre")
        telefono = redis_client.get(sender + "_telefono")
        fecha = redis_client.get(sender + "_fecha")
        hora = redis_client.get(sender + "_hora")
        cliente_id = buscar_cliente(telefono) or crear_cliente(nombre, telefono)

        if cliente_id:
            exito, mensaje = crear_cita(cliente_id, nombre, telefono, fecha, hora, incoming_msg)
        else:
            exito, mensaje = False, "No pude registrar tu cita porque no se pudo crear el cliente."

        respuesta = mensaje

    msg.body(respuesta)
    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
