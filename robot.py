import os
import redis
import requests
import openai
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import re

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
DIRECCION_CLINICA = "📍 Calle Colón 48, entresuelo, Valencia."
GOOGLE_MAPS_LINK = "https://goo.gl/maps/xyz123"

# 📌 **Normalizar formato del teléfono**
def normalizar_telefono(telefono):
    telefono = telefono.replace("whatsapp:", "").strip()
    telefono = re.sub(r"[^\d+]", "", telefono)  # Dejar solo números y "+"
    
    if not telefono.startswith("+34"):  # Ajusta según el país
        telefono = "+34" + telefono
    
    return telefono[:16]  # Koibox no acepta más de 16 caracteres

# 🔍 **Buscar cliente en Koibox**
def buscar_cliente(telefono):
    telefono = normalizar_telefono(telefono)

    cliente_id = redis_client.get(f"cliente_{telefono}")
    if cliente_id:
        return cliente_id

    url = f"{KOIBOX_URL}/clientes/?movil={telefono}"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        clientes_data = response.json()
        if isinstance(clientes_data, list) and len(clientes_data) > 0:
            cliente_id = clientes_data[0].get("id")
            redis_client.set(f"cliente_{telefono}", cliente_id)
            return cliente_id

    return None

# 🆕 **Crear cliente en Koibox**
def crear_cliente(telefono, nombre, notas):
    telefono = normalizar_telefono(telefono)
    
    datos_cliente = {
        "nombre": nombre if nombre else "Cliente WhatsApp",
        "movil": telefono,
        "notas": notas
    }
    response = requests.post(f"{KOIBOX_URL}/clientes/", headers=HEADERS, json=datos_cliente)

    if response.status_code == 201:
        cliente_data = response.json()
        cliente_id = cliente_data.get("id")
        redis_client.set(f"cliente_{telefono}", cliente_id)
        return cliente_id  
    return None

# 📆 **Crear cita en Koibox**
def crear_cita(cliente_id, nombre, telefono, fecha, hora, servicio, notas):
    datos_cita = {
        "fecha": fecha,
        "hora_inicio": hora,
        "titulo": servicio,
        "notas": f"Cita agendada por Gabriel (IA).\n{notas}",
        "user": {"value": GABRIEL_USER_ID, "text": "Gabriel Asistente IA"},
        "cliente": {"value": cliente_id, "text": nombre, "movil": telefono},
        "estado": 1
    }
    
    response = requests.post(f"{KOIBOX_URL}/agenda/", headers=HEADERS, json=datos_cita)
    
    if response.status_code == 201:
        return True, f"✅ ¡Tu cita ha sido creada con éxito!\nNos vemos en {DIRECCION_CLINICA}\n📍 {GOOGLE_MAPS_LINK}"
    else:
        return False, f"⚠️ No se pudo agendar la cita: {response.text}"

# 📩 **Webhook para WhatsApp**
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    sender = request.values.get("From", "")

    resp = MessagingResponse()
    msg = resp.message()

    estado_usuario = redis_client.get(sender + "_estado") or ""
    nombre_usuario = redis_client.get(sender + "_nombre") or ""

    # 📌 **Registrar cliente en Koibox si no existe**
    cliente_id = buscar_cliente(sender)
    if not cliente_id:
        cliente_id = crear_cliente(sender, nombre_usuario, "Cliente registrado a través de WhatsApp con Gabriel IA.")

    # 📌 **Manejo de estados**
    if "limpieza" in incoming_msg:
        redis_client.set(sender + "_servicio", "Limpieza Bucodental")
        redis_client.set(sender + "_estado", "esperando_nombre")
        msg.body("¡Perfecto! Para agendar la cita, ¿puedes decirme tu nombre completo?")
        return str(resp)

    if estado_usuario == "esperando_nombre":
        redis_client.set(sender + "_nombre", incoming_msg)
        redis_client.set(sender + "_estado", "esperando_fecha")
        msg.body(f"¡Gracias, {incoming_msg}! Ahora dime qué día y hora te viene bien para la limpieza bucodental.")
        return str(resp)

    if estado_usuario == "esperando_fecha":
        redis_client.set(sender + "_fecha", incoming_msg)
        redis_client.set(sender + "_estado", "confirmando_cita")
        msg.body(f"¿Te confirmo la cita para el {incoming_msg}? Si es correcto, dime la hora.")
        return str(resp)

    if estado_usuario == "confirmando_cita":
        fecha = redis_client.get(sender + "_fecha")
        nombre = redis_client.get(sender + "_nombre")
        servicio = redis_client.get(sender + "_servicio")

        notas = f"Paciente: {nombre}\nServicio: {servicio}\nFecha y hora: {fecha}\nAgendado por Gabriel IA."
        cliente_id = buscar_cliente(sender)

        if not cliente_id:
            cliente_id = crear_cliente(sender, nombre, notas)

        exito, mensaje = crear_cita(cliente_id, nombre, sender, fecha, incoming_msg, servicio, notas)
        msg.body(mensaje)
        redis_client.delete(sender + "_estado")
        return str(resp)

    # 📌 **Conversación general**
    try:
        respuesta_ia = openai.ChatCompletion.create(
            model="gpt-4-turbo",
            messages=[
                {"role": "system", "content": "Eres Gabriel, el asistente de Sonrisas Hollywood en Valencia. Responde de forma cálida, profesional y útil."},
                {"role": "user", "content": incoming_msg}
            ],
            max_tokens=200
        )
        respuesta_final = respuesta_ia["choices"][0]["message"]["content"].strip()
        msg.body(respuesta_final)

    except Exception as e:
        print(f"⚠️ Error en OpenAI: {e}")
        msg.body("Lo siento, en este momento no puedo responder. Inténtalo más tarde.")

    return str(resp)

# 🚀 **Iniciar aplicación**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
