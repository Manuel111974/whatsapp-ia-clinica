import os
import redis
import requests
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# 🔧 Configuración de Flask
app = Flask(__name__)

# 🔧 Configuración de Redis para memoria de conversación
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# 🔧 Configuración de Koibox API
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"
HEADERS = {
    "X-Koibox-Key": KOIBOX_API_KEY,
    "Content-Type": "application/json"
}

# 📌 Lista de tratamientos de Sonrisas Hollywood
TRATAMIENTOS = {
    "hilos tensores": "Los hilos tensores ayudan a reafirmar y rejuvenecer la piel sin cirugía.",
    "botox": "El Botox suaviza arrugas y líneas de expresión, proporcionando un efecto natural.",
    "ortodoncia invisible": "La ortodoncia invisible como Invisalign alinea los dientes sin brackets.",
    "limpieza dental": "La limpieza dental profesional elimina placa y sarro, manteniendo tu sonrisa sana.",
}

# 📌 Lista de palabras clave para saludos y despedidas
SALUDOS = ["hola", "buenos días", "buenas tardes", "buenas noches", "hey", "qué tal"]
DESPEDIDAS = ["gracias", "ok", "vale", "adiós", "hasta luego"]

# 📌 Función para normalizar teléfonos
def normalizar_telefono(telefono):
    return telefono.strip().replace(" ", "").replace("-", "")

# 📌 Buscar cliente en Koibox
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

# 📌 Crear cliente en Koibox
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

# 📩 Webhook de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    resp = MessagingResponse()
    msg = resp.message()

    estado_usuario = redis_client.get(sender + "_estado")

    # 📌 Responder a saludos
    if incoming_msg in SALUDOS:
        msg.body("¡Hola! 😊 Soy Gabriel, el asistente de Sonrisas Hollywood. ¿En qué puedo ayudarte?")
        return str(resp)

    # 📌 Responder a despedidas
    if incoming_msg in DESPEDIDAS:
        msg.body("¡De nada! Si necesitas algo más, aquí estoy. 😊")
        return str(resp)

    # 📌 Si el usuario pregunta por un tratamiento, Gabriel responde directamente
    for tratamiento in TRATAMIENTOS:
        if tratamiento in incoming_msg:
            msg.body(TRATAMIENTOS[tratamiento])
            return str(resp)

    # 📌 Si pregunta por una oferta, redirigirlo al enlace de Facebook
    if "oferta" in incoming_msg or "promoción" in incoming_msg:
        msg.body("💰 Puedes ver nuestras ofertas aquí: https://www.facebook.com/share/18e8U4AJTN/?mibextid=wwXIfr 📢")
        return str(resp)

    # 📌 Si pregunta por la ubicación
    if "dónde estáis" in incoming_msg or "ubicación" in incoming_msg:
        msg.body("📍 Estamos en Calle Colón 48, Valencia. ¡Te esperamos en Sonrisas Hollywood! 😊")
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

    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
