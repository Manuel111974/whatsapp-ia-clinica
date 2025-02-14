import os
import redis
import requests
import openai
import re
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
    url = f"{KOIBOX_URL}/clientes/"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        clientes_data = response.json()
        for cliente in clientes_data:
            if normalizar_telefono(cliente.get("movil", "")) == telefono:
                return cliente.get("id"), cliente.get("notas", "")
    print(f"⚠️ Cliente no encontrado en Koibox: {telefono}")
    return None, ""

# 🆕 **Crear cliente en Koibox**
def crear_cliente(nombre, telefono, notas="Cliente registrado por Gabriel IA."):
    telefono = normalizar_telefono(telefono)

    datos_cliente = {
        "nombre": nombre,
        "movil": telefono,
        "notas": notas
    }
    response = requests.post(f"{KOIBOX_URL}/clientes/", headers=HEADERS, json=datos_cliente)

    if response.status_code == 201:
        cliente_data = response.json()
        print(f"✅ Cliente creado correctamente en Koibox: {cliente_data}")
        return cliente_data.get("id")
    print(f"❌ Error creando cliente en Koibox: {response.text}")
    return None

# 📆 **Crear cita en Koibox**
def crear_cita(cliente_id, nombre, telefono, fecha, hora, servicio, notas_adicionales):
    datos_cita = {
        "fecha": fecha,
        "hora_inicio": hora,
        "titulo": servicio,
        "notas": f"Cita creada por Gabriel IA. {notas_adicionales}",
        "user": {"value": GABRIEL_USER_ID, "text": "Gabriel Asistente IA"},
        "cliente": {"value": cliente_id, "text": nombre, "movil": telefono},
        "estado": 1  # Estado de cita programada
    }
    
    response = requests.post(f"{KOIBOX_URL}/agenda/", headers=HEADERS, json=datos_cita)
    
    if response.status_code == 201:
        print(f"✅ Cita creada correctamente en Koibox: {response.json()}")
        return f"✅ ¡Tu cita ha sido creada con éxito!\nNos vemos en {DIRECCION_CLINICA}"
    else:
        print(f"❌ Error creando cita en Koibox: {response.text}")
        return f"⚠️ No se pudo agendar la cita: {response.text}"

# 📩 **Webhook para WhatsApp**
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    resp = MessagingResponse()
    msg = resp.message()

    # 📌 **Buscar o registrar cliente en Koibox**
    cliente_id, notas_cliente = buscar_cliente(sender)
    if not cliente_id:
        cliente_id = crear_cliente("Cliente WhatsApp", sender)
        notas_cliente = "Cliente registrado por Gabriel IA."

    # 📌 **Flujo de agendamiento de cita**
    estado_usuario = redis_client.get(sender + "_estado") or ""
    
    if estado_usuario == "confirmando_cita":
        fecha = redis_client.get(sender + "_fecha")
        hora = redis_client.get(sender + "_hora")
        servicio = redis_client.get(sender + "_servicio")
        notas = f"Motivo de la cita: {servicio}. Historial: {notas_cliente}"

        resultado = crear_cita(cliente_id, "Cliente WhatsApp", sender, fecha, hora, servicio, notas)
        msg.body(resultado)

        redis_client.delete(sender + "_estado")
        return str(resp)

    # 📌 **Llamada a IA para responder al usuario**
    contexto = f"Usuario: {incoming_msg}\nHistorial:\n{notas_cliente}"

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

    # 📌 **Actualizar notas en Koibox**
    nuevas_notas = f"{notas_cliente}\nInteracción reciente: {incoming_msg}"
    requests.put(f"{KOIBOX_URL}/clientes/{cliente_id}/", headers=HEADERS, json={"notas": nuevas_notas})

    return str(resp)

# 🚀 **Iniciar aplicación**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
