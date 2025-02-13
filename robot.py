import os
import redis
import requests
import openai
from rapidfuzz import process
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
    telefono = telefono.strip().replace(" ", "").replace("-", "")
    if not telefono.startswith("+34"):
        telefono = "+34" + telefono
    return telefono

# 🔍 **Buscar cliente en Koibox**
def buscar_cliente(telefono):
    telefono = normalizar_telefono(telefono)
    url = f"{KOIBOX_URL}/clientes/"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        clientes_data = response.json()
        if isinstance(clientes_data, list):
            for cliente in clientes_data:
                if normalizar_telefono(cliente.get("movil", "")) == telefono:
                    return cliente.get("id")
    print(f"⚠️ Cliente no encontrado en Koibox: {telefono}")
    return None

# 🆕 **Crear cliente en Koibox**
def crear_cliente(nombre, telefono):
    telefono = normalizar_telefono(telefono)
    datos_cliente = {
        "nombre": nombre,
        "movil": telefono,
        "is_anonymous": False,
        "notas": "Cliente registrado a través de WhatsApp con Gabriel IA."
    }
    response = requests.post(f"{KOIBOX_URL}/clientes/", headers=HEADERS, json=datos_cliente)

    if response.status_code == 201:
        cliente_data = response.json()
        print(f"✅ Cliente creado correctamente: {cliente_data}")
        return cliente_data.get("id")  
    print(f"❌ Error creando cliente en Koibox: {response.text}")
    return None

# 📄 **Obtener lista de servicios desde Koibox**
def obtener_servicios():
    url = f"{KOIBOX_URL}/servicios/"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        servicios_data = response.json()
        if isinstance(servicios_data, list):
            return {s["nombre"]: s["id"] for s in servicios_data}
    print(f"❌ Error obteniendo servicios de Koibox: {response.text}")
    return {}

# 🔍 **Seleccionar el servicio más parecido**
def encontrar_servicio_mas_parecido(servicio_solicitado):
    servicios = obtener_servicios()
    if not servicios:
        return None, "No hay servicios disponibles."

    mejor_match, score, _ = process.extractOne(servicio_solicitado, servicios.keys())

    if score > 75:
        return servicios[mejor_match], f"Se ha seleccionado el servicio más parecido: {mejor_match}"
    
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
        "servicios": [{"value": servicio_id}],
        "estado": 1
    }
    
    response = requests.post(f"{KOIBOX_URL}/agenda/", headers=HEADERS, json=datos_cita)
    
    if response.status_code == 201:
        print(f"✅ Cita creada correctamente en Koibox: {response.json()}")
        return True, f"✅ ¡Tu cita ha sido creada con éxito!\nNos vemos en {DIRECCION_CLINICA}"
    else:
        print(f"❌ Error creando cita en Koibox: {response.text}")
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

    estado_usuario = redis_client.get(sender + "_estado") or ""
    historial = redis_client.get(sender + "_historial") or ""

    # 📌 **Registrar al usuario en Koibox si no existe**
    cliente_id = buscar_cliente(sender)
    if not cliente_id:
        cliente_id = crear_cliente("Cliente WhatsApp", sender)

    # 📌 **Flujo de agendamiento de cita**
    if estado_usuario == "confirmando_cita":
        nombre = redis_client.get(sender + "_nombre")
        telefono = sender
        fecha = redis_client.get(sender + "_fecha")
        hora = redis_client.get(sender + "_hora")
        servicio = redis_client.get(sender + "_servicio")

        exito, mensaje = crear_cita(cliente_id, nombre, telefono, fecha, hora, servicio)
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
    return str(resp)

# 🚀 **Iniciar aplicación**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
