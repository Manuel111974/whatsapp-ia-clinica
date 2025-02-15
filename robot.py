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

# Enlaces útiles
UBICACION_CLINICA = "📍 Nos encontramos en Calle Colón 48, Valencia. También puedes vernos en Google Maps aquí: https://g.co/kgs/U5uMgPg 😊"
OFERTAS_LINK = "💰 Puedes ver nuestras ofertas activas aquí: https://www.facebook.com/share/18e8U4AJTN/?mibextid=wwXIfr 📢"

# 📩 Webhook de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "").replace("whatsapp:", "")

    resp = MessagingResponse()
    msg = resp.message()

    estado_usuario = redis_client.get(sender + "_estado")
    cita_confirmada = redis_client.get(sender + "_cita_confirmada")

    # 📍 Si el usuario pregunta por la ubicación de la clínica
    if any(keyword in incoming_msg for keyword in ["ubicación", "dónde estáis", "cómo llegar", "dirección"]):
        msg.body(UBICACION_CLINICA)
        return str(resp)

    # 🔗 Si el usuario pregunta por las ofertas
    if "oferta" in incoming_msg or "descuento" in incoming_msg:
        msg.body(OFERTAS_LINK)
        return str(resp)

    # 📌 Si el usuario pregunta por su cita
    if "recordar cita" in incoming_msg or "mi cita" in incoming_msg:
        cita = redis_client.get(sender + "_cita_detalles")
        if cita:
            msg.body(f"✅ Tu cita está confirmada: {cita}.\nSi necesitas modificarla, dime qué quieres cambiar: fecha, hora o tratamiento. 😊")
            redis_client.set(sender + "_estado", "modificar_cita", ex=3600)
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
        redis_client.set(sender + "_servicio", incoming_msg, ex=3600)
        actualizar_cita(sender)
        msg.body(f"✅ ¡Tu cita para {incoming_msg} ha sido registrada! 😊")
        return str(resp)

    # 📌 Respuesta con IA para otras preguntas
    respuesta_ia = consultar_openai(incoming_msg)
    if respuesta_ia:
        msg.body(respuesta_ia)
        return str(resp)

    # 📌 Respuesta por defecto
    msg.body("No entendí tu mensaje. ¿Podrías reformularlo? 😊")
    return str(resp)

# 📝 Función para actualizar la cita en Koibox y Redis
def actualizar_cita(sender):
    nombre = redis_client.get(sender + "_nombre")
    telefono = redis_client.get(sender + "_telefono")
    fecha = redis_client.get(sender + "_fecha")
    hora = redis_client.get(sender + "_hora")
    servicio = redis_client.get(sender + "_servicio")

    cliente_id = buscar_cliente(telefono) or crear_cliente(nombre, telefono)
    if cliente_id:
        cita_detalles = f"{nombre} tiene cita para {servicio} el {fecha} a las {hora}."
        redis_client.set(sender + "_cita_detalles", cita_detalles, ex=86400)

        notas = f"✅ Cita actualizada: {servicio} el {fecha} a las {hora}."
        actualizar_notas(cliente_id, notas)

# 🔍 Buscar cliente en Koibox
def buscar_cliente(telefono):
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

# 📝 Actualizar notas en Koibox
def actualizar_notas(cliente_id, notas):
    url = f"{KOIBOX_URL}/clientes/{cliente_id}/"
    response = requests.patch(url, headers=HEADERS, json={"notas": notas})
    return response.status_code == 200

# 🚀 Lanzar aplicación
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
