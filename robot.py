import os
import redis
import requests
import openai
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import json
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
DIRECCION_CLINICA = "📍 Calle Colón 48, entresuelo. 🔔 Pulsa 11 + campana en el telefonillo para subir."

# 📌 **Normalizar formato del teléfono**
def normalizar_telefono(telefono):
    telefono = telefono.replace("whatsapp:", "").strip()
    telefono = re.sub(r"[^\d+]", "", telefono)  # Solo deja números y "+"
    
    if not telefono.startswith("+34"):  # Ajusta según el país
        telefono = "+34" + telefono
    
    return telefono[:16]  # Koibox no acepta más de 16 caracteres

# 🔍 **Buscar cliente en Koibox**
def buscar_cliente(telefono):
    telefono = normalizar_telefono(telefono)
    
    # Primero, revisar en Redis si el cliente ya fue registrado
    cliente_id = redis_client.get(f"cliente_{telefono}")
    if cliente_id:
        print(f"✅ Cliente encontrado en cache: {cliente_id}")
        return cliente_id

    url = f"{KOIBOX_URL}/clientes/"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        clientes_data = response.json()
        if isinstance(clientes_data, list):
            for cliente in clientes_data:
                if normalizar_telefono(cliente.get("movil", "")) == telefono:
                    redis_client.set(f"cliente_{telefono}", cliente["id"])  # Guardamos en Redis
                    print(f"✅ Cliente encontrado en Koibox: {cliente['id']}")
                    return cliente["id"]
    print(f"⚠️ Cliente no encontrado en Koibox: {telefono}")
    return None

# 🆕 **Crear cliente en Koibox**
def crear_cliente(nombre, telefono):
    telefono = normalizar_telefono(telefono)

    if len(telefono) > 16:
        print(f"❌ Error: Número de teléfono excede los 16 caracteres permitidos en Koibox: {telefono}")
        return None

    cliente_id = buscar_cliente(telefono)
    if cliente_id:
        return cliente_id  # Si el cliente ya existe, lo reutilizamos

    datos_cliente = {
        "nombre": nombre,
        "movil": telefono,
        "notas": "Cliente registrado a través de WhatsApp con Gabriel IA."
    }
    response = requests.post(f"{KOIBOX_URL}/clientes/", headers=HEADERS, json=datos_cliente)

    if response.status_code == 201:
        cliente_data = response.json()
        cliente_id = cliente_data.get("id")
        redis_client.set(f"cliente_{telefono}", cliente_id)  # Guardamos en Redis
        print(f"✅ Cliente creado correctamente: {cliente_data}")
        return cliente_id  
    print(f"❌ Error creando cliente en Koibox: {response.text}")
    return None

# 📆 **Crear cita en Koibox**
def crear_cita(cliente_id, fecha, hora, servicio_solicitado):
    datos_cita = {
        "fecha": fecha,
        "hora_inicio": hora,
        "titulo": servicio_solicitado,
        "notas": "Cita agendada por Gabriel (IA)",
        "user": {"value": GABRIEL_USER_ID, "text": "Gabriel Asistente IA"},
        "cliente": {"value": cliente_id},
        "estado": 1
    }
    
    response = requests.post(f"{KOIBOX_URL}/agenda/cita", headers=HEADERS, json=datos_cita)
    
    if response.status_code == 201:
        print(f"✅ Cita creada correctamente en Koibox: {response.json()}")
        return True, f"✅ ¡Tu cita ha sido creada con éxito!\nNos vemos en {DIRECCION_CLINICA}"
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

    # 📌 Obtener estado previo del usuario desde Redis
    estado_usuario = redis_client.get(f"{sender}_estado") or ""
    datos_guardados = redis_client.get(f"{sender}_datos")

    # 📌 Mantener la conversación en memoria
    historial = redis_client.get(f"{sender}_historial") or ""
    historial += f"\nUsuario: {incoming_msg}"
    redis_client.set(f"{sender}_historial", historial)

    cliente_id = buscar_cliente(sender)
    if not cliente_id:
        cliente_id = crear_cliente("Cliente WhatsApp", sender)

    if estado_usuario == "confirmando_cita":
        datos_cita = json.loads(datos_guardados) if datos_guardados else {}
        fecha = datos_cita.get("fecha")
        hora = datos_cita.get("hora")
        servicio = datos_cita.get("servicio")

        exito, mensaje = crear_cita(cliente_id, fecha, hora, servicio)
        msg.body(mensaje)
        redis_client.delete(f"{sender}_estado")
        redis_client.delete(f"{sender}_datos")
        return str(resp)

    # 📌 Construir contexto para la IA
    contexto = f"Usuario: {incoming_msg}\nHistorial:\n{historial}"

    respuesta_ia = openai.ChatCompletion.create(
        model="gpt-4-turbo",
        messages=[
            {"role": "system", "content": "Eres Gabriel, el asistente de Sonrisas Hollywood en Valencia. Responde de forma cálida, profesional y útil."},
            {"role": "user", "content": contexto}
        ],
        max_tokens=200
    )

    respuesta_final = respuesta_ia["choices"][0]["message"]["content"].strip()
    msg.body(respuesta_final)

    return str(resp)

# 🚀 **Iniciar aplicación**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
