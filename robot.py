import os
import redis
import requests
import openai
import dateparser
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from bs4 import BeautifulSoup
from rapidfuzz import process

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

# Información de la clínica
DIRECCION_CLINICA = "Calle Colón 48, Valencia"
TELEFONO_CLINICA = "+34 618 44 93 32"
FACEBOOK_URL = "https://www.facebook.com/share/1BeQpVyja5/?mibextid=wwXIfr"

# 🆕 **Función para obtener ofertas desde Facebook**
def obtener_ofertas():
    try:
        response = requests.get(FACEBOOK_URL)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            ofertas = [element.get_text() for element in soup.find_all("div", class_="x1iorvi4")]
            return ofertas[:3] if ofertas else ["No encontré ofertas activas."]
    except Exception as e:
        return [f"Error al obtener ofertas: {str(e)}"]

# 🔍 **Buscar cliente en Koibox**
def buscar_cliente(telefono):
    url = f"{KOIBOX_URL}/clientes/"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        clientes_data = response.json()
        for cliente in clientes_data.get("results", []):
            if cliente.get("movil") == telefono:
                return cliente
    return None

# 🆕 **Función para registrar notas en Koibox**
def actualizar_notas_cliente(cliente_id, nueva_nota):
    url = f"{KOIBOX_URL}/clientes/{cliente_id}/"
    cliente_data = requests.get(url, headers=HEADERS).json()
    notas_actuales = cliente_data.get("notas", "")
    notas_actualizadas = f"{notas_actuales}\n{nueva_nota}" if notas_actuales else nueva_nota
    
    datos_actualizados = {"notas": notas_actualizadas}
    requests.patch(url, headers=HEADERS, json=datos_actualizados)

# 📄 **Obtener lista de servicios desde Koibox**
def obtener_servicios():
    url = f"{KOIBOX_URL}/servicios/"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        servicios_data = response.json()
        return {s["nombre"]: s["id"] for s in servicios_data["results"]}
    return {}

# 📩 **Webhook de WhatsApp**
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "").replace("whatsapp:", "")
    resp = MessagingResponse()
    msg = resp.message()

    estado_usuario = redis_client.get(sender + "_estado")
    cliente = buscar_cliente(sender)

    # **Respuestas básicas**
    if incoming_msg in ["hola", "buenas", "qué tal", "hey"]:
        msg.body("¡Hola! 😊 Soy Gabriel, el asistente de Sonrisas Hollywood Valencia. ¿En qué puedo ayudarte?\n\n"
                 "1️⃣ Reservar una cita 🗓️\n"
                 "2️⃣ Conocer nuestras ofertas 💰\n"
                 "3️⃣ Ubicación de la clínica 📍\n"
                 "4️⃣ Hablar con un humano 👩‍⚕️")
        return str(resp)

    # **Ubicación**
    if "ubicación" in incoming_msg or "dónde estáis" in incoming_msg:
        msg.body(f"📍 Estamos en *{DIRECCION_CLINICA}*.\n📞 Teléfono: {TELEFONO_CLINICA}")
        return str(resp)

    # **Ofertas**
    if "oferta" in incoming_msg or "promoción" in incoming_msg:
        ofertas = obtener_ofertas()
        msg.body("💰 Ofertas actuales:\n" + "\n".join(ofertas) + f"\n\nPuedes verlas aquí: {FACEBOOK_URL}")
        return str(resp)

    # **Reservar cita para una oferta**
    if "cita" in incoming_msg and "oferta" in incoming_msg:
        redis_client.set(sender + "_estado", "esperando_fecha", ex=600)
        redis_client.set(sender + "_servicio", "Oferta especial")
        msg.body("¡Perfecto! ¿Para qué fecha deseas la cita? 📅 (Ejemplo: '2025-02-17')")
        return str(resp)

    # **Servicios**
    if "servicios" in incoming_msg or "tratamientos" in incoming_msg:
        servicios = obtener_servicios()
        if servicios:
            msg.body("📋 Ofrecemos estos servicios:\n" + "\n".join(servicios.keys()))
        else:
            msg.body("No encontré información de los servicios.")
        return str(resp)

    # **Flujo de reserva**
    if "cita" in incoming_msg or "reservar" in incoming_msg:
        redis_client.set(sender + "_estado", "esperando_servicio", ex=600)
        msg.body("¡Genial! ¿Qué tratamiento necesitas? (Ejemplo: 'Botox', 'Diseño de sonrisa') 💉")
        return str(resp)

    if estado_usuario == "esperando_servicio":
        redis_client.set(sender + "_servicio", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_fecha", ex=600)
        msg.body("¿Para qué fecha deseas la cita? 📅 (Ejemplo: '2025-02-17')")
        return str(resp)

    if estado_usuario == "esperando_fecha":
        redis_client.set(sender + "_fecha", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_hora", ex=600)
        msg.body("¿A qué hora prefieres? ⏰ (Ejemplo: '17:00')")
        return str(resp)

    if estado_usuario == "esperando_hora":
        redis_client.set(sender + "_hora", incoming_msg, ex=600)
        
        if not cliente:
            redis_client.set(sender + "_estado", "esperando_nombre", ex=600)
            msg.body("No encontré tu nombre en nuestra base de datos. ¿Cómo te llamas?")
            return str(resp)
        
        servicio = redis_client.get(sender + "_servicio")
        fecha = redis_client.get(sender + "_fecha")
        hora = redis_client.get(sender + "_hora")

        nota = f"Cita solicitada: {servicio} el {fecha} a las {hora}"
        actualizar_notas_cliente(cliente["id"], nota)

        msg.body(f"✅ Cita registrada para *{cliente['nombre']}*: {servicio} el *{fecha} a las {hora}*.")
        return str(resp)

    # **Respuesta por defecto con IA**
    respuesta_ia = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": incoming_msg}]
    )
    msg.body(respuesta_ia["choices"][0]["message"]["content"])
    
    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
