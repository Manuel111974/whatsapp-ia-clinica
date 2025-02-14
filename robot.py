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
DIRECCION_CLINICA = "📍 Calle Colón 48, entresuelo. 🔔 Pulsa 11 + campana en el telefonillo para subir."

# 📌 **Normalizar formato del teléfono**
def normalizar_telefono(telefono):
    telefono = telefono.replace("whatsapp:", "").strip()
    telefono = re.sub(r"[^\d+]", "", telefono)  # Solo deja números y "+"
    if not telefono.startswith("+34"):
        telefono = "+34" + telefono
    return telefono[:16]

# 🔍 **Buscar cliente en Koibox**
def buscar_cliente(telefono):
    telefono = normalizar_telefono(telefono)
    url = f"{KOIBOX_URL}/clientes/?telefono={telefono}"
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        clientes_data = response.json()
        if clientes_data:
            return clientes_data[0].get("id")
    return None

# 🆕 **Crear cliente en Koibox**
def crear_cliente(nombre, telefono):
    telefono = normalizar_telefono(telefono)
    datos_cliente = {
        "nombre": nombre,
        "movil": telefono,
        "is_anonymous": False,
        "notas": f"Cliente registrado a través de WhatsApp con Gabriel IA."
    }
    response = requests.post(f"{KOIBOX_URL}/clientes/", headers=HEADERS, json=datos_cliente)
    if response.status_code == 201:
        return response.json().get("id")
    return None

# 📌 **Actualizar notas en Koibox**
def actualizar_notas(cliente_id, nuevas_notas):
    url = f"{KOIBOX_URL}/clientes/{cliente_id}/"
    cliente_actual = requests.get(url, headers=HEADERS).json()
    notas_actuales = cliente_actual.get("notas", "")
    notas_actualizadas = f"{notas_actuales}\n{nuevas_notas}".strip()
    
    datos_actualizados = {"notas": notas_actualizadas}
    requests.put(url, headers=HEADERS, json=datos_actualizados)

# 📆 **Crear cita en Koibox**
def crear_cita(cliente_id, nombre, telefono, fecha, hora, motivo):
    datos_cita = {
        "fecha": fecha,
        "hora_inicio": hora,
        "hora_fin": f"{int(hora.split(':')[0]) + 1}:{hora.split(':')[1]}",  # Suma 1h
        "titulo": motivo,
        "notas": f"Cita agendada por Gabriel IA. Motivo: {motivo}",
        "user": {"value": GABRIEL_USER_ID, "text": "Gabriel Asistente IA"},
        "cliente": {"value": cliente_id, "text": nombre, "movil": telefono},
        "estado": 1
    }
    
    response = requests.post(f"{KOIBOX_URL}/agenda/", headers=HEADERS, json=datos_cita)
    if response.status_code == 201:
        actualizar_notas(cliente_id, f"Cita programada el {fecha} a las {hora}. Motivo: {motivo}")
        return True, f"✅ Tu cita ha sido creada con éxito para el {fecha} a las {hora}.\n📍 {DIRECCION_CLINICA}"
    return False, f"⚠️ No se pudo agendar la cita: {response.text}"

# 📩 **Webhook para WhatsApp**
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    resp = MessagingResponse()
    msg = resp.message()

    estado_usuario = redis_client.get(sender + "_estado") or ""
    historial = redis_client.get(sender + "_historial") or ""

    # 📌 **Buscar o crear cliente en Koibox**
    cliente_id = buscar_cliente(sender)
    if not cliente_id:
        msg.body("Parece que no te tenemos registrado. ¿Cuál es tu nombre completo?")
        redis_client.set(sender + "_estado", "esperando_nombre")
        return str(resp)

    # 📌 **Si el estado es "esperando_nombre", guardamos el nombre**
    if estado_usuario == "esperando_nombre":
        nombre = incoming_msg.title()
        cliente_id = crear_cliente(nombre, sender)
        redis_client.set(sender + "_nombre", nombre)
        msg.body(f"¡Gracias {nombre}! Ahora dime, ¿para qué servicio necesitas la consulta?")
        redis_client.set(sender + "_estado", "esperando_motivo")
        return str(resp)

    # 📌 **Si está esperando el motivo de la consulta**
    if estado_usuario == "esperando_motivo":
        motivo = incoming_msg
        redis_client.set(sender + "_motivo", motivo)
        msg.body(f"Perfecto. ¿Para qué fecha y hora deseas la consulta? (Ejemplo: 17/02/2025 a las 19:00)")
        redis_client.set(sender + "_estado", "esperando_fecha")
        return str(resp)

    # 📌 **Si está esperando la fecha y hora**
    if estado_usuario == "esperando_fecha":
        fecha_hora = re.search(r"(\d{1,2}/\d{1,2}/\d{4})\s*a\s*las\s*(\d{1,2}:\d{2})", incoming_msg)
        if fecha_hora:
            fecha = fecha_hora.group(1)
            hora = fecha_hora.group(2)
            redis_client.set(sender + "_fecha", fecha)
            redis_client.set(sender + "_hora", hora)
            msg.body(f"Confirmado: {fecha} a las {hora}. ¿Quieres que procedamos con la reserva?")
            redis_client.set(sender + "_estado", "confirmando_cita")
            return str(resp)
        else:
            msg.body("No pude entender la fecha y hora. Por favor, envíalo en este formato: 17/02/2025 a las 19:00")
            return str(resp)

    # 📌 **Si está en proceso de confirmar la cita**
    if estado_usuario == "confirmando_cita":
        if "sí" in incoming_msg or "confirmar" in incoming_msg:
            nombre = redis_client.get(sender + "_nombre")
            telefono = sender
            fecha = redis_client.get(sender + "_fecha")
            hora = redis_client.get(sender + "_hora")
            motivo = redis_client.get(sender + "_motivo")

            exito, mensaje = crear_cita(cliente_id, nombre, telefono, fecha, hora, motivo)
            msg.body(mensaje)
            redis_client.delete(sender + "_estado")
        else:
            msg.body("Cita cancelada. Si deseas reprogramar, avísame.")
            redis_client.delete(sender + "_estado")
        return str(resp)

    msg.body("No entendí tu mensaje. ¿Cómo puedo ayudarte?")
    return str(resp)

# 🚀 **Iniciar aplicación**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
