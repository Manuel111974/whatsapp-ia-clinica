import os
import redis
import requests
import openai
from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse
import re
import json

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
    telefono = telefono.replace("whatsapp:", "").strip()  # Eliminar "whatsapp:"
    telefono = re.sub(r"[^\d+]", "", telefono)  # Solo deja números y "+"
    
    if not telefono.startswith("+34"):  # Ajusta según el país
        telefono = "+34" + telefono
    
    return telefono[:16]  # Limitar a 16 caracteres

# 🔍 **Buscar cliente en Koibox**
def buscar_cliente(telefono):
    telefono = normalizar_telefono(telefono)
    url = f"{KOIBOX_URL}/clientes/"
    
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        clientes_data = response.json()

        if isinstance(clientes_data, list):
            for cliente in clientes_data:
                if normalizar_telefono(cliente.get("movil", "")) == telefono:
                    return cliente.get("id"), cliente.get("notas", "")
        return None, ""
    except requests.exceptions.RequestException as e:
        print(f"❌ Error buscando cliente en Koibox: {e}")
        return None, ""

# 🆕 **Obtener o crear cliente en Koibox**
def obtener_o_crear_cliente(nombre, telefono):
    telefono = normalizar_telefono(telefono)  # Asegurar formato correcto
    cliente_id, notas_cliente = buscar_cliente(telefono)
    
    if cliente_id:
        return cliente_id, notas_cliente

    print(f"🆕 Creando nuevo cliente en Koibox: {nombre} ({telefono})")

    datos_cliente = {
        "nombre": nombre or "Cliente WhatsApp",
        "movil": telefono,
        "notas": "Cliente registrado por Gabriel IA.",
        "is_active": True,
        "is_anonymous": False,
        "is_suscrito_newsletter": False,
        "is_suscrito_encuestas": False
    }

    # 🔍 Mostrar JSON que se enviará a Koibox
    print(f"📤 Enviando JSON a Koibox: {json.dumps(datos_cliente, indent=2)}")

    try:
        response = requests.post(f"{KOIBOX_URL}/clientes/", headers=HEADERS, json=datos_cliente)
        response.raise_for_status()

        cliente_data = response.json()
        print(f"✅ Cliente creado correctamente en Koibox: {cliente_data}")
        return cliente_data.get("id"), "Cliente registrado por Gabriel IA."

    except requests.exceptions.HTTPError as http_err:
        print(f"❌ Error HTTP creando cliente en Koibox: {http_err}")
        print(f"🔍 Respuesta del servidor: {response.text}")  
    except requests.exceptions.RequestException as e:
        print(f"❌ Error general creando cliente en Koibox: {e}")

    return None, ""

# 📆 **Crear cita en Koibox**
def crear_cita(cliente_id, nombre, telefono, fecha, hora, servicio_solicitado, notas):
    datos_cita = {
        "fecha": fecha,
        "hora_inicio": hora,
        "titulo": servicio_solicitado,
        "notas": f"Cita agendada por Gabriel (IA).\n{notas}",
        "user": {"value": GABRIEL_USER_ID, "text": "Gabriel Asistente IA"},
        "cliente": {"value": cliente_id, "text": nombre, "movil": telefono},
        "estado": 1
    }
    
    try:
        response = requests.post(f"{KOIBOX_URL}/agenda/", headers=HEADERS, json=datos_cita)
        response.raise_for_status()
        return True, f"✅ ¡Tu cita ha sido creada con éxito!\nNos vemos en {DIRECCION_CLINICA}"
    except requests.exceptions.RequestException as e:
        print(f"❌ Error creando cita en Koibox: {e}")
        return False, f"⚠️ No se pudo agendar la cita."

# 📩 **Webhook para WhatsApp**
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    resp = MessagingResponse()
    msg = resp.message()

    estado_usuario = redis_client.get(sender + "_estado") or ""
    historial = redis_client.get(sender + "_historial") or ""

    # 📌 **Registrar al usuario en Koibox si no existe**
    cliente_id, notas_cliente = obtener_o_crear_cliente("Cliente WhatsApp", sender)

    # 📌 **Flujo de agendamiento de cita**
    if estado_usuario == "confirmando_cita":
        nombre = redis_client.get(sender + "_nombre")
        telefono = sender
        fecha = redis_client.get(sender + "_fecha")
        hora = redis_client.get(sender + "_hora")
        servicio = redis_client.get(sender + "_servicio")
        notas = redis_client.get(sender + "_notas") or ""

        exito, mensaje = crear_cita(cliente_id, nombre, telefono, fecha, hora, servicio, notas)
        msg.body(mensaje)
        redis_client.delete(sender + "_estado")
        return str(resp)

    # 📌 **Conversación con IA**
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

    redis_client.set(sender + "_historial", historial + "\n" + incoming_msg)

    return str(resp)

# 🚀 **Iniciar aplicación**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
