import os
import redis
import requests
from bs4 import BeautifulSoup
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from rapidfuzz import process
import openai  # 🔹 Ahora usa IA para respuestas más inteligentes

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

# Configuración de OpenAI (GPT)
openai.api_key = os.getenv("OPENAI_API_KEY")

# Configuración de la Página de Facebook de Sonrisas Hollywood
FACEBOOK_PAGE_URL = "https://www.facebook.com/share/1BeQpVyja5/?mibextid=wwXIfr"

# Información de la clínica
INFO_CLINICA = """
📍 **Ubicación:** Calle Colón 48, Valencia
📞 **Teléfono:** 618 44 93 32
🕒 **Horario:** Lunes a Viernes 10:00 - 20:00
🌍 **Más info:** https://g.co/kgs/U5uMgPg
"""

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
        for cliente in response.json().get("results", []):
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
    return response.json().get("id") if response.status_code == 201 else None

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
    return (servicios[mejor_match], f"Se ha seleccionado el servicio más parecido: {mejor_match}") if score > 75 else (None, "No encontré un servicio similar.")

# 📥 Obtener ofertas desde Facebook
def obtener_ofertas_facebook():
    response = requests.get(FACEBOOK_PAGE_URL)
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, "html.parser")
        ofertas = [post.text.strip() for post in soup.find_all("div", class_="post-content") if "oferta" in post.text.lower()]
        return "\n\n".join(ofertas) if ofertas else "No hay ofertas activas en este momento."
    return "No se pudo acceder a la página de Facebook."

# 🔹 **Usar IA para responder de forma natural**
def generar_respuesta_ia(mensaje):
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "system", "content": "Eres un asistente de una clínica de odontología estética. Responde con amabilidad y profesionalismo."},
                  {"role": "user", "content": mensaje}]
    )
    return response["choices"][0]["message"]["content"]

# 📩 Webhook de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    sender = request.values.get("From", "")

    resp = MessagingResponse()
    msg = resp.message()

    estado_usuario = redis_client.get(sender + "_estado")

    # 📌 Consultas sobre ubicación
    if "dónde" in incoming_msg or "ubicación" in incoming_msg:
        msg.body(INFO_CLINICA)
        return str(resp)

    # 📌 Consultas sobre ofertas
    if "oferta" in incoming_msg or "promoción" in incoming_msg:
        ofertas = obtener_ofertas_facebook()
        msg.body(ofertas if ofertas else "No se encontraron ofertas actuales.")
        return str(resp)

    # 📌 Consultas sobre servicios
    if "servicios" in incoming_msg or "qué ofrecen" in incoming_msg:
        servicios = obtener_servicios()
        if servicios:
            lista_servicios = "\n".join(f"- {s}" for s in servicios.keys())
            msg.body(f"Estos son nuestros servicios:\n{lista_servicios}")
        else:
            msg.body("Actualmente no tengo información de los servicios. ¡Contáctanos!")
        return str(resp)

    # 📌 Consultas generales → **Usar IA para responder**
    respuesta_ia = generar_respuesta_ia(incoming_msg)
    msg.body(respuesta_ia)
    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
