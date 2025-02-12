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
    if not telefono.startswith("+34"):  # Ajustar según el país
        telefono = "+34" + telefono
    return telefono

# 🔍 **Buscar cliente en Koibox**
def buscar_cliente(telefono):
    telefono = normalizar_telefono(telefono)
    url = f"{KOIBOX_URL}/clientes/"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        clientes_data = response.json()
        if "results" in clientes_data and isinstance(clientes_data["results"], list):
            for cliente in clientes_data["results"]:
                if normalizar_telefono(cliente.get("movil", "")) == telefono:
                    return cliente.get("id")  # Devuelve el ID si se encuentra
        return None
    else:
        print(f"❌ Error al obtener clientes de Koibox: {response.text}")
        return None

# 🆕 **Crear cliente en Koibox si no existe**
def crear_cliente(nombre, telefono):
    telefono = normalizar_telefono(telefono)
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
