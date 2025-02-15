import os
import redis
import requests
from rapidfuzz import process
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# Configuración de Flask
app = Flask(__name__)

# Configuración de Redis
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
def crear_cliente(nombre, telefono, notas=""):
    telefono = normalizar_telefono(telefono)
    datos_cliente = {
        "nombre": nombre,
        "movil": telefono,
        "notas": notas,
        "is_anonymous": False
    }
    response = requests.post(f"{KOIBOX_URL}/clientes/", headers=HEADERS, json=datos_cliente)

    if response.status_code == 201:
        return response.json().get("id")
    return None

# 📄 Guardar oferta mencionada en Koibox
def guardar_oferta_en_nota(cliente_id, oferta):
    url = f"{KOIBOX_URL}/clientes/{cliente_id}/"
    response = requests.get(url, headers=HEADERS)
    
    if response.status_code == 200:
        datos_cliente = response.json()
        notas_actuales = datos_cliente.get("notas", "")
        nuevas_notas = notas_actuales + f"\nOferta mencionada: {oferta}"
        
        datos_actualizados = {"notas": nuevas_notas}
        requests.put(url, headers=HEADERS, json=datos_actualizados)

# 📩 Webhook de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    resp = MessagingResponse()
    msg = resp.message()

    estado_usuario = redis_client.get(sender + "_estado")

    # 📌 Si el mensaje menciona ofertas, lo registramos en la ficha del paciente
    if "oferta" in incoming_msg or "promoción" in incoming_msg:
        telefono = sender.replace("whatsapp:", "")
        cliente_id = buscar_cliente(telefono)
        
        if cliente_id:
            guardar_oferta_en_nota(cliente_id, incoming_msg)
            msg.body("✅ He registrado la oferta mencionada en tu ficha. ¿Necesitas más ayuda?")
        else:
            msg.body("❌ No encontré tu ficha en el sistema. ¿Podrías darme tu nombre completo?")
        return str(resp)

    # 📌 Flujo de citas
    if "cita" in incoming_msg or "reservar" in incoming_msg:
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

    if estado_usuario == "esperando_servicio":
        redis_client.set(sender + "_servicio", incoming_msg, ex=600)

        nombre = redis_client.get(sender + "_nombre")
        telefono = redis_client.get(sender + "_telefono")
        fecha = redis_client.get(sender + "_fecha")
        hora = redis_client.get(sender + "_hora")
        servicio = redis_client.get(sender + "_servicio")

        cliente_id = buscar_cliente(telefono) or crear_cliente(nombre, telefono, f"Cita solicitada para {servicio} el {fecha} a las {hora}")

        if cliente_id:
            msg.body(f"✅ Tu cita para {servicio} ha sido registrada para el {fecha} a las {hora}.")
        else:
            msg.body("⚠️ No pude registrar tu cita porque no se pudo crear el cliente.")

        return str(resp)

    # 📌 Respuesta por defecto si no se reconoce el mensaje
    msg.body("No entendí tu mensaje. ¿Podrías reformularlo? 😊")
    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
