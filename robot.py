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

# 🔍 **Buscar cliente en Koibox (corregido)**
def buscar_cliente(telefono):
    telefono = normalizar_telefono(telefono)

    # 📌 Verificar primero en Redis para evitar consultas innecesarias
    cliente_id = redis_client.get(f"cliente_{telefono}")
    if cliente_id:
        print(f"✅ Cliente encontrado en cache: {cliente_id}")
        return cliente_id

    # 📌 Hacer una consulta exacta a Koibox
    url = f"{KOIBOX_URL}/clientes/?movil={telefono}"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        clientes_data = response.json()
        
        if isinstance(clientes_data, list) and len(clientes_data) > 0:
            cliente_id = clientes_data[0].get("id")
            redis_client.set(f"cliente_{telefono}", cliente_id)  # Guardar en cache
            return cliente_id

    print(f"⚠️ Cliente no encontrado en Koibox: {telefono}")
    return None

# 🆕 **Crear cliente en Koibox (ahora lo guarda en Redis)**
def crear_cliente(telefono):
    telefono = normalizar_telefono(telefono)
    
    if len(telefono) > 16:
        print(f"❌ Error: Número de teléfono excede los 16 caracteres permitidos en Koibox: {telefono}")
        return None

    datos_cliente = {
        "nombre": "Cliente WhatsApp",
        "movil": telefono,
        "is_anonymous": False,
        "notas": "Cliente registrado a través de WhatsApp con Gabriel IA."
    }
    response = requests.post(f"{KOIBOX_URL}/clientes/", headers=HEADERS, json=datos_cliente)

    if response.status_code == 201:
        cliente_data = response.json()
        cliente_id = cliente_data.get("id")
        redis_client.set(f"cliente_{telefono}", cliente_id)  # Guardar en cache
        print(f"✅ Cliente creado correctamente: {cliente_data}")
        return cliente_id  
    print(f"❌ Error creando cliente en Koibox: {response.text}")
    return None

# 📆 **Crear cita en Koibox**
def crear_cita(cliente_id, telefono, fecha, hora, servicio, notas):
    datos_cita = {
        "fecha": fecha,
        "hora_inicio": hora,
        "titulo": servicio,
        "notas": f"Cita agendada por Gabriel (IA).\n{notas}",
        "user": {"value": GABRIEL_USER_ID, "text": "Gabriel Asistente IA"},
        "cliente": {"value": cliente_id, "text": "Cliente WhatsApp", "movil": telefono},
        "estado": 1
    }
    
    response = requests.post(f"{KOIBOX_URL}/agenda/", headers=HEADERS, json=datos_cita)
    
    if response.status_code == 201:
        print(f"✅ Cita creada correctamente en Koibox: {response.json()}")
        return True, f"✅ ¡Tu cita ha sido creada con éxito!\nNos vemos en {DIRECCION_CLINICA}\n📍 {GOOGLE_MAPS_LINK}"
    else:
        print(f"❌ Error creando cita en Koibox: {response.text}")
        return False, f"⚠️ No se pudo agendar la cita: {response.text}"

# 📩 **Webhook para WhatsApp**
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    resp = MessagingResponse()
    msg = resp.message()

    estado_usuario = redis_client.get(sender + "_estado") or ""
    notas_usuario = redis_client.get(sender + "_notas") or ""

    # 📌 **Registrar al usuario en Koibox si no existe**
    cliente_id = buscar_cliente(sender)
    if not cliente_id:
        cliente_id = crear_cliente(sender)

    # 📌 **Flujo de agendamiento de cita**
    if estado_usuario == "confirmando_cita":
        fecha = redis_client.get(sender + "_fecha")
        hora = redis_client.get(sender + "_hora")
        servicio = redis_client.get(sender + "_servicio")
        notas = redis_client.get(sender + "_notas") or "Sin notas adicionales"

        exito, mensaje = crear_cita(cliente_id, sender, fecha, hora, servicio, notas)
        msg.body(mensaje)

        redis_client.delete(sender + "_estado")
        return str(resp)

    # 📌 **Manejar solicitud de ubicación**
    if "ubicación" in incoming_msg or "dirección" in incoming_msg:
        msg.body(f"📍 Estamos en {DIRECCION_CLINICA}\n\n📌 Ubicación en Google Maps: {GOOGLE_MAPS_LINK}")
        return str(resp)

    # 📌 **Almacenar notas relevantes**
    if "nota" in incoming_msg or "recordar" in incoming_msg:
        redis_client.set(sender + "_notas", incoming_msg)
        msg.body("📝 Notado. Lo recordaré para tu próxima cita.")

    return str(resp)

# 🚀 **Iniciar aplicación**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
