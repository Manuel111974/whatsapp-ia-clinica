import redis
import requests
import json
from flask import Flask, request

# 🔗 Configuración de Redis (memoria para Gabriel)
REDIS_URL = "redis://TU_URL_DE_RENDER"  # ⚠️ Sustituir con la URL de Redis en Render
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)

# 🔗 Configuración de Koibox (para reservas)
KOIBOX_API_URL = "https://tu-api-koibox.render.com"  # ⚠️ Sustituir con la URL de tu API de Koibox
KOIBOX_API_KEY = "TU_API_KEY"  # ⚠️ Sustituir con tu API Key de Koibox

# 📌 Funciones para guardar y recuperar datos en Redis
def guardar_dato(usuario, clave, valor):
    redis_client.set(f"{usuario}:{clave}", valor)

def obtener_dato(usuario, clave):
    return redis_client.get(f"{usuario}:{clave}")

# 📌 Función para reservar citas en Koibox
def reservar_cita(user_id, fecha, hora, servicio):
    nombre = obtener_dato(user_id, "nombre")
    telefono = obtener_dato(user_id, "telefono")

    if not nombre or not telefono:
        return "Necesito tu nombre y teléfono para reservar la cita. ¿Puedes enviármelo?"

    headers = {"Authorization": f"Bearer {KOIBOX_API_KEY}", "Content-Type": "application/json"}
    data = {
        "nombre": nombre,
        "telefono": telefono,
        "fecha": fecha,
        "hora": hora,
        "servicio": servicio
    }
    response = requests.post(f"{KOIBOX_API_URL}/reservar", headers=headers, data=json.dumps(data))
    
    if response.status_code == 200:
        return f"¡Cita confirmada para {nombre}! 📅 {fecha} a las {hora}. Nos vemos en Calle Colón 48. 😊"
    else:
        return "Lo siento, hubo un problema al reservar. ¿Puedes intentarlo de nuevo?"

# 🚀 Crear API con Flask
app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    user_id = request.form['WaId']  # WhatsApp ID del usuario
    message = request.form['Body'].lower()  # Mensaje recibido

    # 💡 Si el usuario dice "Soy Manuel", Gabriel guarda su nombre
    if "soy" in message:
        nombre = message.split("soy")[-1].strip()
        guardar_dato(user_id, "nombre", nombre)
        return f"¡Encantado, {nombre}! 😊 ¿Cómo puedo ayudarte hoy?"

    # 💡 Si el usuario dice "Mi teléfono es 123456789", Gabriel guarda el número
    if "mi teléfono es" in message:
        telefono = message.split("es")[-1].strip()
        guardar_dato(user_id, "telefono", telefono)
        return f"¡Gracias! Guardé tu número como {telefono}. ¿Quieres reservar una cita?"

    # 💡 Si el usuario pregunta por una cita
    if "quiero una cita" in message or "reserva" in message:
        palabras = message.split()
        fecha, hora, servicio = None, None, None

        for i, palabra in enumerate(palabras):
            if palabra in ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]:
                fecha = palabra
            if ":" in palabra:
                hora = palabra
            if "botox" in palabra:
                servicio = "botox"
            if "diseño" in palabra or "carillas" in palabra:
                servicio = "diseño de sonrisa"

        if fecha and hora and servicio:
            return reservar_cita(user_id, fecha, hora, servicio)
        else:
            return "Para reservar necesito fecha, hora y el tratamiento. ¿Me lo puedes decir?"

    # 💡 Si el usuario pregunta por dirección
    if "dónde estáis" in message or "ubicación" in message:
        return "Nos encontramos en Calle Colón 48, Valencia. 📍 https://goo.gl/maps/aquílalocalización"

    return "¡Hola! Soy Gabriel, el asistente de Sonrisas Hollywood. ¿En qué puedo ayudarte hoy? 😊"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
