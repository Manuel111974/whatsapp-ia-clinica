import os
import redis
import requests
import openai
from rapidfuzz import process
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

# 📌 ID del asistente Gabriel en Koibox
GABRIEL_USER_ID = 1  

# 📌 **Normalizar formato del teléfono**
def normalizar_telefono(telefono):
    telefono = telefono.strip().replace(" ", "").replace("-", "")
    if not telefono.startswith("+34"):
        telefono = "+34" + telefono
    return telefono

# 🔍 **Buscar cliente en Koibox**
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

# 🆕 **Crear cliente en Koibox**
def crear_cliente(nombre, telefono):
    telefono = normalizar_telefono(telefono)
    datos_cliente = {
        "nombre": nombre,
        "movil": telefono,
        "is_anonymous": False
    }
    response = requests.post(f"{KOIBOX_URL}/clientes/", headers=HEADERS, json=datos_cliente)

    if response.status_code == 201:
        return response.json().get("id")
    return None

# 📄 **Obtener lista de servicios desde Koibox**
def obtener_servicios():
    url = f"{KOIBOX_URL}/servicios/"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        servicios_data = response.json()
        if "results" in servicios_data and isinstance(servicios_data["results"], list):
            return {s["nombre"]: s["id"] for s in servicios_data["results"]}
    return {}

# 🔍 **Seleccionar el servicio más parecido**
def encontrar_servicio_mas_parecido(servicio_solicitado):
    servicios = obtener_servicios()
    if not servicios:
        return None, "No hay servicios disponibles."

    mejor_match, score, _ = process.extractOne(servicio_solicitado, servicios.keys())

    if score > 75:
        return servicios[mejor_match], f"Se ha seleccionado el servicio más parecido: {mejor_match}"
    
    return None, "No encontré un servicio similar."

# 📆 **Crear cita en Koibox**
def crear_cita(cliente_id, nombre, telefono, fecha, hora, servicio_solicitado):
    servicio_id, mensaje = encontrar_servicio_mas_parecido(servicio_solicitado)

    if not servicio_id:
        return False, mensaje

    datos_cita = {
        "fecha": fecha,
        "hora_inicio": hora,
        "hora_fin": calcular_hora_fin(hora, 1),
        "titulo": servicio_solicitado,
        "notas": "Cita agendada por Gabriel (IA)",
        "user": {"value": GABRIEL_USER_ID, "text": "Gabriel Asistente IA"},
        "cliente": {"value": cliente_id, "text": nombre, "movil": telefono},
        "servicios": [{"value": servicio_id}],
        "estado": 1
    }
    
    response = requests.post(f"{KOIBOX_URL}/agenda/cita", headers=HEADERS, json=datos_cita)
    
    if response.status_code == 201:
        return True, "✅ ¡Tu cita ha sido creada con éxito!"
    else:
        return False, f"⚠️ No se pudo agendar la cita: {response.text}"

# ⏰ **Calcular hora de finalización**
def calcular_hora_fin(hora_inicio, duracion_horas):
    h, m = map(int, hora_inicio.split(":"))
    h += duracion_horas
    return f"{h:02d}:{m:02d}"

# 📩 **Webhook para WhatsApp con Memoria Mejorada + IA**
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    resp = MessagingResponse()
    msg = resp.message()

    estado_usuario = redis_client.get(sender + "_estado") or ""
    historial = redis_client.get(sender + "_historial") or ""

    # 📌 **Guardar memoria de conversación**
    historial += f"\nUsuario: {incoming_msg}"
    redis_client.set(sender + "_historial", historial, ex=3600)

    # 📌 **Respuestas fijas para preguntas comunes**
    if "ubicación" in incoming_msg or "dónde están" in incoming_msg or "dirección" in incoming_msg:
        msg.body("📍 Nuestra clínica Sonrisas Hollywood está en **Calle Colón 48, Valencia**. ¡Te esperamos! 😊")
        return str(resp)

    if "cómo llegar" in incoming_msg:
        msg.body("📍 Estamos en **Calle Colón 48, Valencia**. Puedes llegar en metro (Colón), autobús o en coche. Hay parkings cercanos como el de El Corte Inglés y el de la Calle Cirilo Amorós. 🚗🚌🚶‍♂️")
        return str(resp)

    # 📌 **Conversación natural usando IA**
    contexto = f"Usuario: {incoming_msg}\nHistorial:\n{historial}\nNota: La clínica Sonrisas Hollywood está en Calle Colón 48, Valencia."
    
    respuesta_ia = openai.ChatCompletion.create(
        model="gpt-4-turbo",
        messages=[
            {"role": "system", "content": "Eres Gabriel, el asistente de Sonrisas Hollywood en Valencia. Responde de forma cálida, profesional y útil. La clínica está en Calle Colón 48, Valencia."},
            {"role": "user", "content": contexto}
        ],
        max_tokens=150
    )

    respuesta_final = respuesta_ia["choices"][0]["message"]["content"].strip()

    msg.body(respuesta_final)
    return str(resp)

# 🚀 **Iniciar aplicación**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
