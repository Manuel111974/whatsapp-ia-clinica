import os
import redis
import requests
import openai
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from fuzzywuzzy import process  # 🔹 Para comparar tratamientos con fuzzy matching

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

# 📌 ID del empleado "Gabriel Asistente IA" en Koibox
GABRIEL_USER_ID = 23527  # ⚠️ REEMPLAZAR CON EL ID REAL

# 🔍 **Obtener lista de servicios disponibles en Koibox**
def obtener_servicios():
    url = f"{KOIBOX_URL}/servicios/"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        try:
            servicios_data = response.json()
            if "results" in servicios_data and isinstance(servicios_data["results"], list):
                return {servicio["nombre"].lower(): servicio["id"] for servicio in servicios_data["results"]}
        except Exception as e:
            print(f"❌ Error procesando la respuesta de Koibox (Servicios): {e}")
    else:
        print(f"❌ Error al obtener servicios de Koibox: {response.text}")

    return {}

# Cargar los servicios disponibles en Koibox
SERVICIOS_DISPONIBLES = obtener_servicios()

# 🔍 **Buscar el servicio más similar al ingresado por el cliente**
def encontrar_servicio_mas_parecido(nombre_servicio):
    mejor_coincidencia, similitud = process.extractOne(nombre_servicio.lower(), SERVICIOS_DISPONIBLES.keys())

    if similitud > 70:  # Si la coincidencia es superior al 70%, lo usamos
        return mejor_coincidencia, SERVICIOS_DISPONIBLES[mejor_coincidencia]
    else:
        return "Primera Visita", SERVICIOS_DISPONIBLES.get("primera visita", None)

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
                        return cliente.get("id")
        except Exception as e:
            print(f"❌ Error procesando la respuesta de Koibox (Clientes): {e}")
    else:
        print(f"❌ Error al obtener clientes de Koibox: {response.text}")

    return None  # Si no encuentra el cliente, retorna None

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

# 📆 **Crear cita en Koibox**
def crear_cita(cliente_id, fecha, hora, servicio_nombre):
    # ✅ Convertir fecha al formato correcto (YYYY-MM-DD)
    try:
        fecha_formateada = "-".join(reversed(fecha.split("/")))  # Convierte 'DD/MM/YYYY' a 'YYYY-MM-DD'
    except Exception as e:
        print(f"❌ Error formateando la fecha: {e}")
        return False, "⚠️ La fecha ingresada no es válida. Usa el formato DD/MM/YYYY."

    # ✅ Buscar el servicio más parecido
    servicio_encontrado, servicio_id = encontrar_servicio_mas_parecido(servicio_nombre)

    if not servicio_id:
        return False, "⚠️ No encontramos un servicio similar. Se ha asignado una 'Primera Visita'."

    datos_cita = {
        "titulo": f"Cita para {servicio_encontrado}",  # ✅ Se agregó un título obligatorio
        "fecha": fecha_formateada,
        "hora_inicio": hora,
        "hora_fin": calcular_hora_fin(hora, 1),  # Duración de 1 hora
        "notas": "Cita agendada por Gabriel (IA)",
        "user": GABRIEL_USER_ID,  # ✅ ID directo
        "cliente": cliente_id,  # ✅ ID directo
        "servicios": [servicio_id],  # ✅ ID en lista
        "estado": 1  # ✅ Estado programado
    }

    response = requests.post(f"{KOIBOX_URL}/agenda/", headers=HEADERS, json=datos_cita)

    if response.status_code == 201:
        return True, f"✅ ¡Tu cita para {servicio_encontrado} ha sido creada con éxito!"
    else:
        print(f"❌ Error al agendar la cita: {response.text}")
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
        respuesta = "¡Perfecto! ¿Qué día prefieres? 📅 (Ejemplo: '12/02/2025')"

    elif redis_client.get(sender + "_estado") == "esperando_fecha":
        redis_client.set(sender + "_fecha", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_hora", ex=600)
        respuesta = "Genial. ¿A qué hora te gustaría la cita? ⏰ (Ejemplo: '16:00')"

    elif redis_client.get(sender + "_estado") == "esperando_hora":
        redis_client.set(sender + "_hora", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_servicio", ex=600)
        respuesta = "¿Qué tratamiento necesitas? (Ejemplo: 'Botox', 'Diseño de sonrisa') 💉."

    elif redis_client.get(sender + "_estado") == "esperando_servicio":
        exito, mensaje = crear_cita(buscar_cliente(redis_client.get(sender + "_telefono")), redis_client.get(sender + "_fecha"), redis_client.get(sender + "_hora"), redis_client.get(sender + "_servicio"))
        respuesta = mensaje

    msg.body(respuesta)
    return str(resp)

# 🚀 **Iniciar aplicación**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
