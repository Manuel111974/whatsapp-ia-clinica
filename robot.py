import os
import redis
import requests
from rapidfuzz import process  # 🔹 Alternativa más rápida y sin dependencias problemáticas
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# 📌 Configuración de Flask
app = Flask(__name__)

# 📌 Configuración de Redis para la memoria temporal
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# 📌 Configuración de Koibox API
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")
KOIBOX_URL = "https://api.koibox.cloud/api"

HEADERS = {
    "X-Koibox-Key": KOIBOX_API_KEY,
    "Content-Type": "application/json"
}

# 📌 ID del empleado "Gabriel Asistente IA" en Koibox (REEMPLAZAR SI ES NECESARIO)
GABRIEL_USER_ID = 1  # ⚠️ REEMPLAZAR CON EL ID REAL

# 🔍 **Buscar cliente en Koibox**
def buscar_cliente(telefono):
    url = f"{KOIBOX_URL}/clientes/"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        try:
            clientes_data = response.json()
            if "results" in clientes_data and isinstance(clientes_data["results"], list):
                clientes = clientes_data["results"]
                for cliente in clientes:
                    if cliente.get("movil") == telefono:
                        return cliente.get("id")  # Devuelve el ID del cliente si lo encuentra
            else:
                print(f"⚠️ Estructura inesperada en la respuesta de Koibox: {clientes_data}")
                return None
        except Exception as e:
            print(f"❌ Error procesando la respuesta de Koibox: {e}")
            return None
    else:
        print(f"❌ Error al obtener clientes de Koibox: {response.text}")
        return None

# 🆕 **Crear cliente en Koibox si no existe**
def crear_cliente(nombre, telefono):
    datos_cliente = {
        "nombre": nombre,
        "movil": telefono,
        "is_anonymous": False
    }
    response = requests.post(f"{KOIBOX_URL}/clientes/", headers=HEADERS, json=datos_cliente)
    
    if response.status_code == 201:
        return response.json().get("id")  # Devuelve el ID del cliente recién creado
    else:
        print(f"❌ Error creando cliente en Koibox: {response.text}")
        return None

# 📄 **Obtener lista de servicios desde Koibox**
def obtener_servicios():
    url = f"{KOIBOX_URL}/servicios/"
    response = requests.get(url, headers=HEADERS)
    
    if response.status_code == 200:
        try:
            servicios_data = response.json()
            if "results" in servicios_data and isinstance(servicios_data["results"], list):
                return {s["nombre"]: s["id"] for s in servicios_data["results"]}
        except Exception as e:
            print(f"❌ Error procesando la respuesta de servicios Koibox: {e}")
            return {}
    else:
        print(f"❌ Error al obtener servicios de Koibox: {response.text}")
        return {}

# 🔍 **Seleccionar el servicio más parecido al solicitado**
def encontrar_servicio_mas_parecido(servicio_solicitado):
    servicios = obtener_servicios()
    if not servicios:
        return None, "No se encontraron servicios disponibles."
    
    mejor_match, score, id_servicio = process.extractOne(servicio_solicitado, servicios.keys())
    
    if score > 75:  # Ajustar el umbral de similitud si es necesario
        return servicios[mejor_match], f"Se ha seleccionado el servicio más parecido: {mejor_match}"
    
    return None, "No encontré un servicio similar. ¿Podrías reformularlo?"

# 📆 **Crear cita en Koibox**
def crear_cita(cliente_id, fecha, hora, servicio_solicitado):
    servicio_id, mensaje = encontrar_servicio_mas_parecido(servicio_solicitado)
    
    if not servicio_id:
        return False, mensaje

    datos_cita = {
        "fecha": fecha,
        "hora_inicio": hora,
        "hora_fin": calcular_hora_fin(hora, 1),  # Duración 1 hora por defecto
        "titulo": servicio_solicitado,
        "notas": "Cita agendada por Gabriel (IA)",
        "user": GABRIEL_USER_ID,  # Ajustado al formato requerido
        "cliente": cliente_id,
        "servicios": [servicio_id],
        "estado": 1  # Ajustado al formato requerido
    }
    
    response = requests.post(f"{KOIBOX_URL}/agenda/", headers=HEADERS, json=datos_cita)
    
    if response.status_code == 201:
        return True, "✅ ¡Tu cita ha sido creada con éxito!"
    else:
        return False, f"⚠️ No se pudo agendar la cita: {response.text}"

# ⏰ **Función para calcular la hora de finalización**
def calcular_hora_fin(hora_inicio, duracion_horas):
    h, m = map(int, hora_inicio.split(":"))
    h += duracion_horas
    return f"{h:02d}:{m:02d}"

# 📩 **Webhook para recibir mensajes de WhatsApp**
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    # Inicializar respuesta de Twilio
    resp = MessagingResponse()
    msg = resp.message()
    respuesta = "No entendí tu mensaje. ¿Puedes reformularlo? 😊"

    # Obtener historial del usuario en Redis
    historial = redis_client.get(sender) or ""

    # **Flujo de citas**
    if "cita" in incoming_msg or "reservar" in incoming_msg:
        redis_client.set(sender + "_estado", "esperando_nombre", ex=600)
        respuesta = "¡Genial! Primero dime tu nombre completo 😊."

    elif redis_client.get(sender + "_estado") == "esperando_nombre":
        redis_client.set(sender + "_nombre", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_telefono", ex=600)
        respuesta = f"Gracias, {incoming_msg} 😊. Ahora dime tu número de teléfono 📞."

    elif redis_client.get(sender + "_estado") == "esperando_telefono":
        redis_client.set(sender + "_telefono", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_fecha", ex=600)
        respuesta = "¡Perfecto! ¿Qué día prefieres? 📅 (Ejemplo: '2025-02-12')"

    elif redis_client.get(sender + "_estado") == "esperando_fecha":
        redis_client.set(sender + "_fecha", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_hora", ex=600)
        respuesta = "Genial. ¿A qué hora te gustaría la cita? ⏰ (Ejemplo: '16:00')"

    elif redis_client.get(sender + "_estado") == "esperando_hora":
        redis_client.set(sender + "_hora", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_servicio", ex=600)
        respuesta = "¿Qué tratamiento necesitas? (Ejemplo: 'Botox', 'Diseño de sonrisa') 💉."

    elif redis_client.get(sender + "_estado") == "esperando_servicio":
        redis_client.set(sender + "_servicio", incoming_msg, ex=600)

        nombre = redis_client.get(sender + "_nombre")
        telefono = redis_client.get(sender + "_telefono")
        fecha = redis_client.get(sender + "_fecha")
        hora = redis_client.get(sender + "_hora")
        servicio = redis_client.get(sender + "_servicio")

        cliente_id = buscar_cliente(telefono) or crear_cliente(nombre, telefono)
        exito, mensaje = crear_cita(cliente_id, fecha, hora, servicio) if cliente_id else (False, "No pude registrar tu cita.")

        respuesta = mensaje

    msg.body(respuesta)
    return str(resp)

# 🚀 **Iniciar aplicación**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
