import os
import redis
import requests
from rapidfuzz import process
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
GABRIEL_USER_ID = 1  # ⚠️ REEMPLAZAR SI ES NECESARIO

# 📌 Normalizar formato del teléfono
def normalizar_telefono(telefono):
    telefono = telefono.strip().replace(" ", "").replace("-", "")
    if not telefono.startswith("+34"):
        telefono = "+34" + telefono
    return telefono

# 🔍 **Buscar cliente en Koibox**
def buscar_cliente(telefono):
    telefono = normalizar_telefono(telefono)
    print(f"🔍 Buscando cliente en Koibox con teléfono: {telefono}")
    url = f"{KOIBOX_URL}/clientes/"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        clientes_data = response.json()
        for cliente in clientes_data.get("results", []):
            if normalizar_telefono(cliente.get("movil")) == telefono:
                print(f"✅ Cliente encontrado: {cliente['text']} (ID: {cliente['value']})")
                return cliente["value"]
    print("⚠️ Cliente no encontrado en Koibox.")
    return None

# 🆕 **Crear cliente en Koibox si no existe**
def crear_cliente(nombre, telefono):
    telefono = normalizar_telefono(telefono)
    print(f"➕ Creando nuevo cliente: {nombre} - {telefono}")
    datos_cliente = {"nombre": nombre, "movil": telefono, "is_anonymous": False}
    response = requests.post(f"{KOIBOX_URL}/clientes/", headers=HEADERS, json=datos_cliente)

    if response.status_code == 201:
        cliente_id = response.json().get("value")
        print(f"✅ Cliente creado con éxito: ID {cliente_id}")
        return cliente_id
    print(f"❌ Error creando cliente en Koibox: {response.text}")
    return None

# 📄 **Obtener lista de servicios desde Koibox**
def obtener_servicios():
    print("📡 Obteniendo lista de servicios de Koibox...")
    url = f"{KOIBOX_URL}/servicios/"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        servicios_data = response.json()
        if "results" in servicios_data:
            servicios = {s["text"].lower(): s["value"] for s in servicios_data["results"] if s["is_active"]}
            print(f"✅ Servicios obtenidos: {servicios}")
            return servicios
    print(f"❌ Error obteniendo servicios: {response.text}")
    return {}

# 🔍 **Seleccionar el servicio más parecido**
def encontrar_servicio_mas_parecido(servicio_solicitado):
    servicios = obtener_servicios()
    if not servicios:
        return None, "No se encontraron servicios disponibles en Koibox."

    print(f"🔎 Buscando coincidencia para el servicio: {servicio_solicitado}")
    mejor_match, score, _ = process.extractOne(servicio_solicitado.lower(), servicios.keys())

    if score > 75:
        print(f"✅ Servicio encontrado: {mejor_match} (ID {servicios[mejor_match]})")
        return servicios[mejor_match], f"Se ha seleccionado el servicio más parecido: {mejor_match}"
    
    print("❌ No se encontró un servicio similar.")
    return None, "No encontré un servicio similar."

# 📆 **Crear cita en Koibox**
def crear_cita(cliente_id, nombre, telefono, fecha, hora, servicio_solicitado):
    servicio_id, mensaje = encontrar_servicio_mas_parecido(servicio_solicitado)

    if not servicio_id:
        return False, mensaje

    datos_cita = {
        "fecha": fecha,
        "hora_inicio": hora,
        "hora_fin": calcular_hora_fin(hora, 1),
        "titulo": servicio_solicitado,
        "notas": "Cita agendada por Gabriel (IA)",
        "user": {"value": GABRIEL_USER_ID, "text": "Gabriel Asistente IA"},
        "cliente": {"value": cliente_id, "text": nombre, "movil": telefono},
        "servicios": [{"value": servicio_id, "text": servicio_solicitado}],
        "estado": {"value": 1, "nombre": "Confirmada"}
    }

    print(f"📤 Enviando cita a Koibox: {datos_cita}")

    response = requests.post(f"{KOIBOX_URL}/agenda/", headers=HEADERS, json=datos_cita)

    if response.status_code == 201:
        print(f"✅ Cita creada con éxito: {response.json()}")
        return True, "✅ ¡Tu cita ha sido creada con éxito!"
    else:
        print(f"❌ Error creando la cita en Koibox: {response.text}")
        return False, f"⚠️ No se pudo agendar la cita: {response.text}"

# ⏰ **Calcular hora de finalización**
def calcular_hora_fin(hora_inicio, duracion_horas):
    h, m = map(int, hora_inicio.split(":"))
    h += duracion_horas
    return f"{h:02d}:{m:02d}"

# 📩 **Webhook para WhatsApp**
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    resp = MessagingResponse()
    msg = resp.message()
    respuesta = "No entendí tu mensaje. ¿Puedes reformularlo? 😊"

    estado = redis_client.get(sender + "_estado")

    if "cita" in incoming_msg or "reservar" in incoming_msg:
        redis_client.set(sender + "_estado", "esperando_nombre", ex=600)
        respuesta = "¡Genial! Primero dime tu nombre completo 😊."

    elif estado == "esperando_servicio":
        redis_client.set(sender + "_servicio", incoming_msg, ex=600)

        servicio = redis_client.get(sender + "_servicio")
        print(f"📩 Servicio recibido del usuario: {servicio}")

        nombre = redis_client.get(sender + "_nombre")
        telefono = redis_client.get(sender + "_telefono")
        fecha = redis_client.get(sender + "_fecha")
        hora = redis_client.get(sender + "_hora")

        cliente_id = buscar_cliente(telefono) or crear_cliente(nombre, telefono)

        if cliente_id:
            exito, mensaje = crear_cita(cliente_id, nombre, telefono, fecha, hora, servicio)
        else:
            exito, mensaje = False, "No pude registrar tu cita porque no se pudo crear el cliente."

        respuesta = mensaje

    msg.body(respuesta)
    return str(resp)

# 🚀 **Iniciar aplicación**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
