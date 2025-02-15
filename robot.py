import os
import redis
import requests
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from openai import OpenAI

# Configuración de Flask
app = Flask(__name__)

# Configuración de Redis (Memoria a corto plazo)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Configuración de Koibox API
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"

HEADERS = {
    "X-Koibox-Key": KOIBOX_API_KEY,
    "Content-Type": "application/json"
}

# ID de Gabriel en Koibox
GABRIEL_USER_ID = 1  # ⚠️ REEMPLAZAR con el ID correcto

# API Key de OpenAI para mejorar la IA
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Enlace a las ofertas
OFERTAS_URL = "https://www.facebook.com/share/18e8U4AJTN/?mibextid=wwXIfr"

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
        if "results" in clientes_data and isinstance(clientes_data["results"], list):
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

# 📄 Guardar notas en la ficha del paciente
def agregar_nota_cliente(cliente_id, nota):
    url = f"{KOIBOX_URL}/clientes/{cliente_id}/"
    response = requests.get(url, headers=HEADERS)
    
    if response.status_code == 200:
        cliente_data = response.json()
        notas_actuales = cliente_data.get("notas", "")
        nueva_nota = f"{notas_actuales}\n{nota}" if notas_actuales else nota

        # Actualizar la ficha con la nueva nota
        response = requests.patch(url, headers=HEADERS, json={"notas": nueva_nota})
        return response.status_code == 200
    return False

# 📩 Función para interpretar el mensaje con IA
def interpretar_mensaje(mensaje):
    response = openai_client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "Eres un asistente de atención al cliente para una clínica de estética y odontología."},
            {"role": "user", "content": mensaje}
        ]
    )
    return response.choices[0].message["content"]

# 📩 Webhook de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    sender = request.values.get("From", "")
    telefono = sender.replace("whatsapp:", "")

    resp = MessagingResponse()
    msg = resp.message()

    # Memoria de conversación con Redis
    estado_usuario = redis_client.get(f"{telefono}_estado")
    cliente_id = buscar_cliente(telefono) or crear_cliente("Paciente WhatsApp", telefono)

    # 📌 Pasar el mensaje por la IA para interpretarlo
    respuesta_ia = interpretar_mensaje(incoming_msg)

    # 📌 Respuestas más naturales a saludos
    saludos = ["hola", "buenas", "qué tal", "hey"]
    if any(s in incoming_msg.lower() for s in saludos):
        if not redis_client.get(f"{telefono}_saludo"):
            msg.body(f"¡Hola! 😊 Soy Gabriel, el asistente de Sonrisas Hollywood. ¿En qué puedo ayudarte?")
            redis_client.set(f"{telefono}_saludo", "1", ex=600)
        else:
            msg.body("¡Hola de nuevo! ¿En qué puedo ayudarte esta vez?")
        return str(resp)

    # 📌 Pregunta sobre ofertas
    if "oferta" in incoming_msg or "promoción" in incoming_msg:
        nota = f"Paciente preguntó por ofertas: {incoming_msg}"
        agregar_nota_cliente(cliente_id, nota)
        msg.body(f"💰 Aquí puedes ver nuestras ofertas actuales: {OFERTAS_URL}")
        return str(resp)

    # 📌 Flujo de citas
    if "cita" in incoming_msg or "reservar" in incoming_msg:
        redis_client.set(f"{telefono}_estado", "esperando_servicio", ex=600)
        msg.body("¡Genial! ¿Qué tratamiento necesitas? (Ejemplo: 'Botox', 'Diseño de sonrisa') 💉")
        return str(resp)

    if estado_usuario == "esperando_servicio":
        redis_client.set(f"{telefono}_servicio", incoming_msg, ex=600)
        redis_client.set(f"{telefono}_estado", "esperando_fecha", ex=600)
        msg.body("¿Para qué fecha deseas la cita? 📅 (Ejemplo: '2025-02-17')")
        return str(resp)

    if estado_usuario == "esperando_fecha":
        redis_client.set(f"{telefono}_fecha", incoming_msg, ex=600)
        redis_client.set(f"{telefono}_estado", "esperando_hora", ex=600)
        msg.body("¿A qué hora prefieres? ⏰ (Ejemplo: '17:00')")
        return str(resp)

    if estado_usuario == "esperando_hora":
        redis_client.set(f"{telefono}_hora", incoming_msg, ex=600)
        redis_client.set(f"{telefono}_estado", "confirmando_cita", ex=600)

        # Recuperar datos almacenados en Redis
        servicio = redis_client.get(f"{telefono}_servicio")
        fecha = redis_client.get(f"{telefono}_fecha")
        hora = redis_client.get(f"{telefono}_hora")

        nota = f"Paciente solicitó cita para {servicio} el {fecha} a las {hora}."
        agregar_nota_cliente(cliente_id, nota)

        msg.body(f"Voy a registrar tu cita para {servicio} el {fecha} a las {hora}. Un momento... ⏳")
        return str(resp)

    # 📌 Respuesta flexible con IA
    msg.body(respuesta_ia)
    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
