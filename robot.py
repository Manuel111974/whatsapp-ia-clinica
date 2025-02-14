import os
import redis
import requests
from bs4 import BeautifulSoup
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from rapidfuzz import process

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

# Configuración de la Página de Facebook de Sonrisas Hollywood
FACEBOOK_PAGE_URL = "https://www.facebook.com/share/1BeQpVyja5/?mibextid=wwXIfr"

# ID de Gabriel en Koibox
GABRIEL_USER_ID = 1  # ⚠️ REEMPLAZAR con el ID correcto

# 📌 Normalizar teléfono
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
        for cliente in clientes_data.get("results", []):
            if normalizar_telefono(cliente.get("movil")) == telefono:
                return cliente.get("id")
    return None

# 🆕 Crear cliente en Koibox
def crear_cliente(nombre, telefono):
    telefono = normalizar_telefono(telefono)
    datos_cliente = {
        "nombre": nombre,
        "movil": telefono,
        "notas": "Cliente registrado por Gabriel IA.",
        "is_active": True,
    }
    response = requests.post(f"{KOIBOX_URL}/clientes/", headers=HEADERS, json=datos_cliente)
    if response.status_code == 201:
        return response.json().get("id")
    return None

# 📄 Obtener lista de servicios desde Koibox
def obtener_servicios():
    url = f"{KOIBOX_URL}/servicios/"
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        return {s["nombre"]: s["id"] for s in response.json().get("results", [])}
    return {}

# 🔍 Seleccionar el servicio más parecido
def encontrar_servicio_mas_parecido(servicio_solicitado):
    servicios = obtener_servicios()
    if not servicios:
        return None, "No hay servicios disponibles."
    
    mejor_match, score, _ = process.extractOne(servicio_solicitado, servicios.keys())
    if score > 75:
        return servicios[mejor_match], f"Se ha seleccionado el servicio más parecido: {mejor_match}"
    return None, "No encontré un servicio similar."

# 📆 Crear cita en Koibox y actualizar notas
def crear_cita(cliente_id, nombre, telefono, fecha, hora, servicio_solicitado):
    servicio_id, mensaje = encontrar_servicio_mas_parecido(servicio_solicitado)
    if not servicio_id:
        return False, mensaje

    datos_cita = {
        "fecha": fecha,
        "hora_inicio": hora,
        "hora_fin": calcular_hora_fin(hora, 1),
        "titulo": servicio_solicitado,
        "notas": f"Cita agendada por Gabriel IA para {nombre} ({telefono})",
        "user": {"value": GABRIEL_USER_ID, "text": "Gabriel Asistente IA"},
        "cliente": {"value": cliente_id, "text": nombre, "movil": telefono},
        "servicios": [{"value": servicio_id}],
        "estado": 1
    }
    
    response = requests.post(f"{KOIBOX_URL}/agenda/cita/", headers=HEADERS, json=datos_cita)
    
    if response.status_code == 201:
        # Actualizar notas en la ficha del paciente
        actualizar_notas_cliente(cliente_id, f"Agendada cita para {fecha} a las {hora} - Servicio: {servicio_solicitado}")
        return True, "✅ ¡Tu cita ha sido creada con éxito!"
    return False, f"⚠️ No se pudo agendar la cita: {response.text}"

# ⏰ Calcular hora de finalización
def calcular_hora_fin(hora_inicio, duracion_horas):
    h, m = map(int, hora_inicio.split(":"))
    h += duracion_horas
    return f"{h:02d}:{m:02d}"

# 📝 Actualizar notas en la ficha del cliente
def actualizar_notas_cliente(cliente_id, nota):
    url = f"{KOIBOX_URL}/clientes/{cliente_id}/"
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        cliente_data = response.json()
        notas_actuales = cliente_data.get("notas", "")
        nuevas_notas = f"{notas_actuales}\n{nota}"
        requests.put(url, headers=HEADERS, json={"notas": nuevas_notas})

# 📩 Webhook de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    resp = MessagingResponse()
    msg = resp.message()

    # 📌 Si el usuario pregunta por ofertas
    if "oferta" in incoming_msg:
        ofertas = obtener_ofertas_facebook()
        msg.body(ofertas if ofertas else "No se encontraron ofertas actuales.")
        return str(resp)

    # 📌 Si el usuario quiere reservar una cita
    if "cita" in incoming_msg or "reservar" in incoming_msg:
        redis_client.set(sender + "_estado", "esperando_nombre", ex=600)
        msg.body("¡Genial! Primero dime tu nombre completo 😊.")
        return str(resp)

    # 📌 Respuesta por defecto
    msg.body("No entendí tu mensaje. ¿Podrías reformularlo? 😊")
    return str(resp)

# 📥 Obtener ofertas desde la página de Facebook
def obtener_ofertas_facebook():
    response = requests.get(FACEBOOK_PAGE_URL)
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, "html.parser")
        ofertas = []
        for post in soup.find_all("div", class_="post-content"):
            if "oferta" in post.text.lower():
                ofertas.append(post.text.strip())
        return "\n\n".join(ofertas) if ofertas else "No hay ofertas activas en este momento."
    return "No se pudo acceder a la página de Facebook."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
