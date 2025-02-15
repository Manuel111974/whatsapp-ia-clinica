import os
import redis
import requests
import openai
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# 🔧 Configuración de Flask
app = Flask(__name__)

# 🔧 Configuración de Redis (memoria a corto plazo para recordar las conversaciones)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# 🔧 Configuración de Koibox API
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"
HEADERS = {
    "X-Koibox-Key": KOIBOX_API_KEY,
    "Content-Type": "application/json"
}

# 🔧 Configuración de OpenAI (para mejorar respuestas)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

# 📌 ID de usuario para registrar las citas en Koibox
GABRIEL_USER_ID = 1  

# 📌 Función para normalizar teléfonos
def normalizar_telefono(telefono):
    return telefono.strip().replace(" ", "").replace("-", "")

# 🔍 Buscar cliente en Koibox
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

# 🆕 Crear cliente en Koibox
def crear_cliente(nombre, telefono):
    telefono = normalizar_telefono(telefono)
    datos_cliente = {
        "nombre": nombre,
        "movil": telefono,
        "notas": "Registrado por Gabriel IA",
        "is_active": True,
        "is_anonymous": False
    }
    response = requests.post(f"{KOIBOX_URL}/clientes/", headers=HEADERS, json=datos_cliente)
    return response.json().get("id") if response.status_code == 201 else None

# 📌 Guardar notas en la ficha del paciente en Koibox
def actualizar_notas_cliente(cliente_id, nueva_nota):
    url = f"{KOIBOX_URL}/clientes/{cliente_id}/"
    response = requests.get(url, headers=HEADERS)
    
    if response.status_code == 200:
        datos_cliente = response.json()
        notas_actuales = datos_cliente.get("notas", "")
        notas_actualizadas = f"{notas_actuales}\n{nueva_nota}"
        datos_cliente["notas"] = notas_actualizadas
        requests.put(url, headers=HEADERS, json=datos_cliente)

# 📆 Crear cita en Koibox
def crear_cita(cliente_id, nombre, telefono, fecha, hora, servicio):
    datos_cita = {
        "fecha": fecha,
        "hora_inicio": hora,
        "hora_fin": calcular_hora_fin(hora, 1),
        "titulo": servicio,
        "notas": f"Cita creada por Gabriel IA para {servicio}.",
        "user": {"value": GABRIEL_USER_ID, "text": "Gabriel Asistente IA"},
        "cliente": {
            "value": cliente_id,
            "text": nombre,
            "movil": telefono
        },
        "estado": 1
    }
    
    response = requests.post(f"{KOIBOX_URL}/agenda/cita/", headers=HEADERS, json=datos_cita)
    return response.status_code == 201

# ⏰ Calcular hora de finalización
def calcular_hora_fin(hora_inicio, duracion_horas):
    h, m = map(int, hora_inicio.split(":"))
    h += duracion_horas
    return f"{h:02d}:{m:02d}"

# 🤖 **Función para generar respuestas con IA**
def generar_respuesta_ia(mensaje_usuario):
    prompt = f"""
    Eres Gabriel, un asistente IA de Sonrisas Hollywood. Responde a las preguntas de los pacientes de manera profesional y amigable.
    
    Paciente: {mensaje_usuario}
    Gabriel:"""
    
    response = openai.Completion.create(
        engine="text-davinci-003",
        prompt=prompt,
        max_tokens=100
    )
    
    return response["choices"][0]["text"].strip()

# 📩 Webhook de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    resp = MessagingResponse()
    msg = resp.message()

    estado_usuario = redis_client.get(sender + "_estado")

    # **Usamos IA para entender preguntas generales**
    if estado_usuario is None:
        respuesta_ia = generar_respuesta_ia(incoming_msg)
        msg.body(respuesta_ia)
        return str(resp)

    # 📌 Flujo de reservas
    if "cita" in incoming_msg:
        redis_client.set(sender + "_estado", "esperando_nombre", ex=600)
        msg.body("¡Genial! Primero dime tu nombre completo 😊.")
        return str(resp)

    if estado_usuario == "esperando_nombre":
        redis_client.set(sender + "_nombre", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_telefono", ex=600)
        msg.body(f"Gracias, {incoming_msg}. Ahora dime tu número de teléfono 📞.")
        return str(resp)

    if estado_usuario == "esperando_telefono":
        redis_client.set(sender + "_telefono", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_fecha", ex=600)
        msg.body("¡Perfecto! ¿Qué día prefieres? 📅 (Ejemplo: '2025-02-14')")
        return str(resp)

    if estado_usuario == "esperando_fecha":
        redis_client.set(sender + "_fecha", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_hora", ex=600)
        msg.body("Genial. ¿A qué hora te gustaría la cita? ⏰ (Ejemplo: '11:00')")
        return str(resp)

    if estado_usuario == "esperando_hora":
        redis_client.set(sender + "_hora", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_servicio", ex=600)
        msg.body("¿Qué tratamiento necesitas? (Ejemplo: 'Botox', 'Diseño de sonrisa') 💉.")
        return str(resp)

    if estado_usuario == "esperando_servicio":
        redis_client.set(sender + "_servicio", incoming_msg, ex=600)

        nombre = redis_client.get(sender + "_nombre")
        telefono = redis_client.get(sender + "_telefono")
        fecha = redis_client.get(sender + "_fecha")
        hora = redis_client.get(sender + "_hora")
        servicio = redis_client.get(sender + "_servicio")

        cliente_id = buscar_cliente(telefono) or crear_cliente(nombre, telefono)

        if cliente_id:
            exito = crear_cita(cliente_id, nombre, telefono, fecha, hora, servicio)
            if exito:
                actualizar_notas_cliente(cliente_id, f"Cita para {servicio} el {fecha} a las {hora}.")
                msg.body(f"✅ Cita registrada para {servicio} el {fecha} a las {hora}. ¡Nos vemos pronto! 😊")
            else:
                msg.body("⚠️ No se pudo registrar la cita. Inténtalo de nuevo.")
        else:
            msg.body("⚠️ No pude registrar tu cita porque no se pudo crear el cliente.")

        return str(resp)

    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
