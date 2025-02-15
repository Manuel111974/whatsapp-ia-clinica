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

# 📌 Información de la clínica
DIRECCION_CLINICA = "Calle Colón 48, Valencia"
TELEFONO_CLINICA = "+34 618 44 93 32"
FACEBOOK_URL = "https://www.facebook.com/share/1BeQpVyja5/?mibextid=wwXIfr"

# 📢 Función para obtener ofertas desde Facebook
def obtener_ofertas():
    try:
        response = requests.get(FACEBOOK_URL)
        soup = BeautifulSoup(response.text, 'html.parser')
        ofertas = soup.find_all("div", class_="offer")  # Ajusta la clase según la estructura de Facebook
        if ofertas:
            return "\n".join([oferta.text.strip() for oferta in ofertas[:3]])  
        return "No encontré ofertas activas en este momento."
    except Exception:
        return "No pude obtener las ofertas en este momento. Puedes verlas aquí: " + FACEBOOK_URL

# 📄 Obtener lista de servicios desde Koibox
def obtener_servicios():
    url = f"{KOIBOX_URL}/servicios/"
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        servicios_data = response.json()
        return {s["nombre"].lower(): s["id"] for s in servicios_data["results"]}
    return {}

# 🔍 Seleccionar el servicio más parecido
def encontrar_servicio(servicio_solicitado):
    servicios = obtener_servicios()
    mejor_match, score, _ = process.extractOne(servicio_solicitado.lower(), servicios.keys())
    if score > 75:
        return servicios[mejor_match], mejor_match
    return None, None

# 📆 Crear cita en Koibox
def crear_cita(cliente_id, nombre, telefono, fecha, hora, servicio_solicitado):
    servicio_id, servicio_nombre = encontrar_servicio(servicio_solicitado)
    if not servicio_id:
        return False, "No encontré un servicio similar en nuestro catálogo."

    datos_cita = {
        "fecha": fecha,
        "hora_inicio": hora,
        "hora_fin": f"{int(hora.split(':')[0]) + 1}:{hora.split(':')[1]}",  
        "titulo": servicio_nombre,
        "notas": f"Cita agendada por Gabriel IA para {servicio_solicitado}",
        "cliente": {"value": cliente_id, "text": nombre, "movil": telefono},
        "servicios": [{"value": servicio_id}],
        "estado": 1
    }
    
    response = requests.post(f"{KOIBOX_URL}/agenda/cita/", headers=HEADERS, json=datos_cita)
    return response.status_code == 201, f"✅ Cita para {servicio_solicitado} registrada el {fecha} a las {hora}."

# 📩 Webhook de WhatsApp con IA
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    resp = MessagingResponse()
    msg = resp.message()

    if incoming_msg in ["hola", "buenas", "qué tal", "hey"]:
        msg.body("¡Hola! 😊 Soy Gabriel, el asistente de Sonrisas Hollywood Valencia. ¿En qué puedo ayudarte?\n\n"
                 "1️⃣ Reservar una cita 🗓️\n"
                 "2️⃣ Conocer nuestras ofertas 💰\n"
                 "3️⃣ Ubicación de la clínica 📍\n"
                 "4️⃣ Hablar con un especialista 👩‍⚕️")
        return str(resp)

    if "oferta" in incoming_msg:
        ofertas = obtener_ofertas()
        msg.body(f"💰 Ofertas actuales:\n{ofertas}")
        return str(resp)

    if "servicios" in incoming_msg or "qué hacéis" in incoming_msg:
        servicios = "\n".join(obtener_servicios().keys())
        msg.body(f"📌 Estos son algunos de nuestros servicios:\n{servicios}")
        return str(resp)

    if "ubicación" in incoming_msg or "dónde estáis" in incoming_msg:
        msg.body(f"📍 Estamos en: {DIRECCION_CLINICA}\n📞 Teléfono: {TELEFONO_CLINICA}")
        return str(resp)

    if "cita" in incoming_msg or "reservar" in incoming_msg:
        redis_client.set(sender + "_estado", "esperando_servicio", ex=600)
        msg.body("¡Genial! ¿Qué tratamiento necesitas? (Ejemplo: 'Botox', 'Diseño de sonrisa') 💉")
        return str(resp)

    estado_usuario = redis_client.get(sender + "_estado")

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
        servicio = redis_client.get(sender + "_servicio")
        fecha = redis_client.get(sender + "_fecha")
        hora = incoming_msg

        cliente_id = 1  # Suponiendo un ID de cliente ya registrado

        exito, mensaje = crear_cita(cliente_id, "Cliente WhatsApp", sender, fecha, hora, servicio)
        msg.body(mensaje)
        return str(resp)

    msg.body("No entendí tu mensaje. ¿Podrías reformularlo? 😊")
    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
