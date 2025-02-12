import os
import redis
import requests
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# 📌 Configuración de Flask
app = Flask(__name__)

# 📌 Configuración de Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# 📌 Configuración de Koibox API
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"

HEADERS = {
    "X-Koibox-Key": KOIBOX_API_KEY,
    "Content-Type": "application/json"
}

# 📌 ID del empleado "Gabriel Asistente IA" en Koibox
GABRIEL_USER_ID = 1

# 📌 Normalizar formato del teléfono
def normalizar_telefono(telefono):
    telefono = telefono.strip().replace(" ", "").replace("-", "")
    if not telefono.startswith("+34"):
        telefono = "+34" + telefono
    return telefono

# 📌 Obtener servicios de Koibox con 2 intentos
def obtener_servicios():
    url = f"{KOIBOX_URL}/servicios/"
    for intento in range(2):  # 🔁 Reintentar una vez si falla
        response = requests.get(url, headers=HEADERS)

        if response.status_code == 200:
            servicios_data = response.json()
            if "results" in servicios_data and isinstance(servicios_data["results"], list):
                return {s["nombre"]: s["id"] for s in servicios_data["results"]}
        
        print(f"⚠️ Intento {intento+1}: Error al obtener servicios de Koibox: {response.status_code}")
        print(f"🔴 Respuesta de Koibox: {response.content}")

    return {}

# 📆 **Crear cita en Koibox**
def crear_cita(cliente_id, nombre, telefono, fecha, hora, servicio_solicitado):
    servicios = obtener_servicios()

    if not servicios:
        return False, "⚠️ No pude obtener la lista de servicios. Inténtalo más tarde."

    servicio_id = servicios.get(servicio_solicitado)

    if not servicio_id:
        return False, f"⚠️ No encontré el servicio '{servicio_solicitado}', intenta con otro nombre."

    datos_cita = {
        "fecha": fecha,
        "hora_inicio": hora,
        "hora_fin": calcular_hora_fin(hora, 1),
        "titulo": servicio_solicitado,
        "notas": "Cita agendada por Gabriel (IA)",
        "user": {"value": GABRIEL_USER_ID, "text": "Gabriel Asistente IA"},
        "cliente": {
            "value": cliente_id,
            "text": nombre,
            "movil": telefono
        },
        "servicios": [{"value": servicio_id}],
        "estado": 1
    }
    
    response = requests.post(f"{KOIBOX_URL}/agenda/", headers=HEADERS, json=datos_cita)
    
    if response.status_code == 201:
        return True, "✅ ¡Tu cita ha sido creada con éxito!"
    else:
        return False, f"⚠️ No se pudo agendar la cita: {response.text}"

# ⏰ **Calcular hora de finalización**
def calcular_hora_fin(hora_inicio, duracion_horas):
    h, m = map(int, hora_inicio.split(":"))
    h += duracion_horas
    return f"{h:02d}:{m:02d}"

# 📩 **Webhook para WhatsApp**
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        incoming_msg = request.values.get("Body", "").strip()
        sender = request.values.get("From", "")

        print(f"📩 Mensaje recibido de {sender}: {incoming_msg}")

        resp = MessagingResponse()
        msg = resp.message()
        estado = redis_client.get(sender + "_estado")

        if estado is None:
            redis_client.set(sender + "_estado", "inicio")
            estado = "inicio"

        if estado == "inicio":
            redis_client.set(sender + "_estado", "esperando_nombre")
            msg.body("¡Hola! Para agendar una cita, dime tu nombre completo 😊.")

        elif estado == "esperando_nombre":
            redis_client.set(sender + "_nombre", incoming_msg)
            redis_client.set(sender + "_estado", "esperando_telefono")
            msg.body(f"Gracias, {incoming_msg}. Ahora dime tu número de teléfono 📞.")

        elif estado == "esperando_telefono":
            redis_client.set(sender + "_telefono", incoming_msg)
            redis_client.set(sender + "_estado", "esperando_fecha")
            msg.body("¡Perfecto! ¿Qué día prefieres para la cita? 📅 (Ejemplo: '2025-02-14')")

        elif estado == "esperando_fecha":
            redis_client.set(sender + "_fecha", incoming_msg)
            redis_client.set(sender + "_estado", "esperando_hora")
            msg.body("¿A qué hora te gustaría la cita? ⏰ (Ejemplo: '11:00')")

        elif estado == "esperando_hora":
            redis_client.set(sender + "_hora", incoming_msg)
            redis_client.set(sender + "_estado", "esperando_servicio")
            msg.body("¿Qué tratamiento necesitas? 💉 (Ejemplo: 'Diseño de sonrisa')")

        elif estado == "esperando_servicio":
            redis_client.set(sender + "_servicio", incoming_msg)

            nombre = redis_client.get(sender + "_nombre")
            telefono = redis_client.get(sender + "_telefono")
            fecha = redis_client.get(sender + "_fecha")
            hora = redis_client.get(sender + "_hora")
            servicio = redis_client.get(sender + "_servicio")

            cliente_id = buscar_cliente(telefono) or crear_cliente(nombre, telefono)

            if cliente_id:
                exito, mensaje = crear_cita(cliente_id, nombre, telefono, fecha, hora, servicio)
            else:
                exito, mensaje = False, "No pude registrar tu cita porque no se pudo crear el cliente."

            msg.body(mensaje)
            redis_client.delete(sender + "_estado")

        return str(resp)

    except Exception as e:
        print(f"⚠️ Error en webhook: {str(e)}")
        return "Error interno", 500

# 🚀 **Iniciar aplicación**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
