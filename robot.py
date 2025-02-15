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

# Enlace de Facebook para ofertas
OFERTAS_LINK = "https://www.facebook.com/share/18e8U4AJTN/?mibextid=wwXIfr"

# 📩 Webhook de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "").replace("whatsapp:", "")

    resp = MessagingResponse()
    msg = resp.message()

    estado_usuario = redis_client.get(sender + "_estado")

    # 📌 Si el usuario pregunta por ofertas
    if "oferta" in incoming_msg or "promoción" in incoming_msg or "descuento" in incoming_msg:
        msg.body(f"💰 Puedes ver nuestras ofertas aquí: {OFERTAS_LINK} 📢")
        redis_client.set(sender + "_mencion_oferta", "Sí", ex=3600)
        return str(resp)

    # 📌 Si el usuario pregunta por su cita
    if "recordar cita" in incoming_msg or "mi cita" in incoming_msg:
        cita = redis_client.get(sender + "_cita_detalles")
        if cita:
            msg.body(f"✅ Tu cita está confirmada: {cita}")
        else:
            msg.body("⚠️ No encontré una cita registrada para ti. ¿Quieres reservar una ahora?")
        return str(resp)

    # 📌 Ubicación
    if "dónde estáis" in incoming_msg or "ubicación" in incoming_msg:
        msg.body("📍 Nos encontramos en Calle Colón 48, Valencia. También puedes vernos aquí: https://g.co/kgs/U5uMgPg 😊")
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

        # 📌 Guardar datos en Koibox SOLO UNA VEZ
        nombre = redis_client.get(sender + "_nombre")
        telefono = redis_client.get(sender + "_telefono")
        fecha = redis_client.get(sender + "_fecha")
        hora = redis_client.get(sender + "_hora")

        cita_detalles = f"{nombre} ha reservado una cita para {servicio} el {fecha} a las {hora}."
        redis_client.set(sender + "_cita_detalles", cita_detalles, ex=86400)

        cliente_id = buscar_cliente(telefono) or crear_cliente(nombre, telefono)
        if cliente_id:
            notas = f"✅ Cita registrada: {servicio} el {fecha} a las {hora}."
            if redis_client.get(sender + "_mencion_oferta"):
                notas += " 📌 El paciente mencionó una oferta."

            actualizar_notas(cliente_id, notas)
            msg.body(f"✅ ¡Tu cita para {servicio} ha sido registrada el {fecha} a las {hora}! 😊")
        else:
            msg.body("⚠️ No se pudo completar la cita. Por favor, intenta nuevamente.")

        return str(resp)

    # 📌 Cualquier otro mensaje después de la cita NO se registra en notas
    if redis_client.get(sender + "_cita_detalles"):
        msg.body("Estoy aquí para ayudarte con cualquier otra duda sobre nuestros tratamientos 😊.")
        return str(resp)

    # 📌 Respuesta con IA si no está en un flujo de reserva de cita
    respuesta_ia = consultar_openai(incoming_msg)
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

# 📝 Actualizar notas en Koibox SOLO UNA VEZ
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
