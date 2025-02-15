import os
import redis
import requests
import openai
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# Configuración de Flask
app = Flask(__name__)

# Configuración de Redis (Memoria de Gabriel)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Configuración de Koibox API
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"
HEADERS = {
    "X-Koibox-Key": KOIBOX_API_KEY,
    "Content-Type": "application/json"
}

# Configuración de OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

# ID de Gabriel en Koibox (Reemplazar con el real)
GABRIEL_USER_ID = 1  

# 📩 Webhook de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    sender = request.values.get("From", "").replace("whatsapp:", "")

    resp = MessagingResponse()
    msg = resp.message()

    estado_usuario = redis_client.get(sender + "_estado")

    # 📌 Procesamiento de respuesta con OpenAI
    respuesta_ia = consultar_openai(incoming_msg)

    # 📌 Si el usuario quiere recordar su cita
    if "recordar cita" in incoming_msg or "mi cita" in incoming_msg:
        cita = redis_client.get(sender + "_cita_detalles")
        if cita:
            msg.body(f"✅ Tu cita está confirmada: {cita}")
        else:
            msg.body("⚠️ No encontré una cita registrada para ti. ¿Quieres reservar una ahora?")
        return str(resp)

    # 📌 Flujo de reserva de cita
    if "cita" in incoming_msg or "reservar" in incoming_msg:
        redis_client.set(sender + "_estado", "esperando_nombre", ex=3600)
        msg.body("¡Genial! Primero dime tu nombre completo 😊.")
        return str(resp)

    if estado_usuario == "esperando_nombre":
        redis_client.set(sender + "_nombre", incoming_msg, ex=3600)
        redis_client.set(sender + "_estado", "esperando_telefono", ex=3600)
        msg.body(f"Gracias, {incoming_msg}. Ahora dime tu número de teléfono 📞.")
        return str(resp)

    if estado_usuario == "esperando_telefono":
        redis_client.set(sender + "_telefono", incoming_msg, ex=3600)
        redis_client.set(sender + "_estado", "esperando_fecha", ex=3600)
        msg.body("¡Perfecto! ¿Qué día prefieres? 📅 (Ejemplo: '2025-02-14')")
        return str(resp)

    if estado_usuario == "esperando_fecha":
        redis_client.set(sender + "_fecha", incoming_msg, ex=3600)
        redis_client.set(sender + "_estado", "esperando_hora", ex=3600)
        msg.body("Genial. ¿A qué hora te gustaría la cita? ⏰ (Ejemplo: '11:00')")
        return str(resp)

    if estado_usuario == "esperando_hora":
        redis_client.set(sender + "_hora", incoming_msg, ex=3600)
        redis_client.set(sender + "_estado", "esperando_servicio", ex=3600)
        msg.body("¿Qué tratamiento necesitas? (Ejemplo: 'Botox', 'Diseño de sonrisa') 💉.")
        return str(resp)

    if estado_usuario == "esperando_servicio":
        servicio = incoming_msg
        redis_client.set(sender + "_servicio", servicio, ex=3600)

        # 📌 Guardar notas en Koibox
        nombre = redis_client.get(sender + "_nombre")
        telefono = redis_client.get(sender + "_telefono")
        fecha = redis_client.get(sender + "_fecha")
        hora = redis_client.get(sender + "_hora")

        conversacion = redis_client.get(sender + "_conversacion") or ""
        conversacion += f"\n{nombre} ha pedido {servicio} el {fecha} a las {hora}."

        cita_detalles = f"{nombre} ha reservado una cita para {servicio} el {fecha} a las {hora}."
        redis_client.set(sender + "_cita_detalles", cita_detalles, ex=86400)

        cliente_id = buscar_cliente(telefono) or crear_cliente(nombre, telefono)
        if cliente_id:
            actualizar_notas(cliente_id, conversacion)
            msg.body(f"✅ ¡Tu cita para {servicio} ha sido registrada el {fecha} a las {hora}! 😊")
        else:
            msg.body("⚠️ No se pudo completar la cita. Por favor, intenta nuevamente.")

        return str(resp)

    # 📌 Respuesta con IA si no está en un flujo de reserva de cita
    if respuesta_ia:
        msg.body(respuesta_ia)
        return str(resp)

    # 📌 Respuesta por defecto
    msg.body("No entendí tu mensaje. ¿Podrías reformularlo? 😊")
    return str(resp)

# 🔍 Buscar cliente en Koibox
def buscar_cliente(telefono):
    telefono = telefono.strip().replace(" ", "").replace("-", "")
    url = f"{KOIBOX_URL}/clientes/"
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        clientes_data = response.json()
        for cliente in clientes_data.get("results", []):
            if cliente.get("movil") == telefono:
                return cliente.get("id")
    return None

# 🆕 Crear cliente en Koibox
def crear_cliente(nombre, telefono):
    datos_cliente = {"nombre": nombre, "movil": telefono, "notas": "Cliente registrado por Gabriel IA."}
    response = requests.post(f"{KOIBOX_URL}/clientes/", headers=HEADERS, json=datos_cliente)
    return response.json().get("id") if response.status_code == 201 else None

# 📝 Actualizar notas en Koibox con la conversación
def actualizar_notas(cliente_id, notas):
    url = f"{KOIBOX_URL}/clientes/{cliente_id}/"
    response = requests.patch(url, headers=HEADERS, json={"notas": notas})
    return response.status_code == 200

# 🤖 Procesamiento con OpenAI
def consultar_openai(mensaje):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Eres Gabriel, el asistente de Sonrisas Hollywood."},
                {"role": "user", "content": mensaje}
            ]
        )
        return response['choices'][0]['message']['content'].strip()
    except Exception as e:
        return "Lo siento, no puedo procesar tu solicitud en este momento."

# 🚀 Lanzar aplicación
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
