import os
import redis
import requests
import openai
from datetime import datetime
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# Configuración de Flask
app = Flask(__name__)

# Configuración de Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Configuración de OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

# Configuración de Koibox API
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"
HEADERS = {
    "X-Koibox-Key": KOIBOX_API_KEY,
    "Content-Type": "application/json"
}

# ID de Gabriel en Koibox
GABRIEL_USER_ID = 1  # ⚠️ REEMPLAZAR con el ID correcto

# 📌 Función para normalizar teléfonos
def normalizar_telefono(telefono):
    telefono = telefono.strip().replace(" ", "").replace("-", "")
    if not telefono.startswith("+34"):  
        telefono = "+34" + telefono
    return telefono

# 🔍 Buscar cliente en Koibox
def buscar_cliente(telefono):
    telefono = normalizar_telefono(telefono)
    url = f"{KOIBOX_URL}/clientes/"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        clientes_data = response.json()
        if "results" in clientes_data:
            for cliente in clientes_data["results"]:
                if normalizar_telefono(cliente.get("movil")) == telefono:
                    return cliente.get("id")
    return None

# 🆕 Crear cliente en Koibox
def crear_cliente(nombre, telefono):
    telefono = normalizar_telefono(telefono)
    datos_cliente = {
        "nombre": nombre,
        "movil": telefono,
        "notas": "Cliente registrado por Gabriel IA.",
        "is_active": True
    }
    response = requests.post(f"{KOIBOX_URL}/clientes/", headers=HEADERS, json=datos_cliente)

    if response.status_code == 201:
        return response.json().get("id")
    return None

# 📄 Guardar notas en la ficha del paciente en Koibox
def guardar_notas_en_koibox(cliente_id, notas):
    url = f"{KOIBOX_URL}/clientes/{cliente_id}/"
    datos_actualizados = {"notas": notas}
    requests.patch(url, headers=HEADERS, json=datos_actualizados)

# 🧠 Función para consultar OpenAI y mejorar respuestas
def generar_respuesta_openai(mensaje):
    prompt = f"""
    Eres Gabriel, el asistente virtual de Sonrisas Hollywood. Responde con amabilidad y claridad.
    Pregunta del usuario: "{mensaje}"
    Respuesta:
    """
    respuesta = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "system", "content": prompt}],
        temperature=0.7,
        max_tokens=100
    )
    return respuesta["choices"][0]["message"]["content"]

# 📩 Webhook de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    resp = MessagingResponse()
    msg = resp.message()

    # Mantener memoria de la conversación en Redis
    historial = redis_client.get(sender + "_historial") or ""
    historial += f"\nCliente: {incoming_msg}"

    # Procesar mensaje con OpenAI
    if "cita" in incoming_msg or "reservar" in incoming_msg:
        redis_client.set(sender + "_estado", "esperando_nombre", ex=600)
        msg.body("¡Genial! Primero dime tu nombre completo 😊.")
        return str(resp)

    estado_usuario = redis_client.get(sender + "_estado")

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
            nota_paciente = f"""
            📅 Cita programada:
            - Nombre: {nombre}
            - Teléfono: {telefono}
            - Fecha: {fecha}
            - Hora: {hora}
            - Tratamiento: {servicio}
            - Agendada por Gabriel IA 🤖
            """
            guardar_notas_en_koibox(cliente_id, nota_paciente)
            msg.body(f"✅ ¡Tu cita ha sido registrada! Nos vemos el {fecha} a las {hora}.")
        else:
            msg.body("⚠️ No pude registrar tu cita. Por favor, intenta de nuevo.")

        return str(resp)

    # 📌 Consultar OpenAI para respuestas naturales
    respuesta_ai = generar_respuesta_openai(incoming_msg)
    msg.body(respuesta_ai)

    return str(resp)

# 🚀 Ejecutar la aplicación
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
