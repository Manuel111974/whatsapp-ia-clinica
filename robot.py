import os
import redis
import openai
import requests
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# Configuración de Flask
app = Flask(__name__)

# Configuración de Redis (Para recordar la conversación)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Configuración de OpenAI (GPT-4)
openai.api_key = os.getenv("OPENAI_API_KEY")

# Configuración de Airtable
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")  
AIRTABLE_BASE_ID = "appLzlE5aJOuFkSZb"  
AIRTABLE_TABLE_ID = "tblhdHTMAwFxBxJly"  

# URL de la API de Airtable
AIRTABLE_URL = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_ID}"

# Headers de autenticación para Airtable
AIRTABLE_HEADERS = {
    "Authorization": f"Bearer {AIRTABLE_API_KEY}",
    "Content-Type": "application/json"
}

# IDs de los campos en Airtable
FIELDS = {
    "nombre": "fldcnZz38hH0Ggqaj",
    "telefono": "fldNjWFRNcriIDMqf",
    "fecha": "fldfoFgZZ9a5V37cq",
    "hora": "fldEXJh063AXZ7IDw",
    "interes": "fldLAUkuJ6dUe1BH4",
    "estado": "fld311mg19eXxHWr",
    "notas": "fldB9uItP4dhQDnCu"
}

# Función para verificar si el paciente ya está registrado en Airtable
def buscar_cliente_telefono(telefono):
    url = f"{AIRTABLE_URL}?filterByFormula=({FIELDS['telefono']}='{telefono}')"
    response = requests.get(url, headers=AIRTABLE_HEADERS)

    if response.status_code == 200:
        records = response.json().get("records", [])
        if records:
            return records[0]["id"]  # Devuelve el ID del cliente si existe
    return None  # Cliente no encontrado

# Función para registrar un nuevo cliente en Airtable
def registrar_cliente_airtable(nombre, telefono):
    datos_cliente = {
        "records": [
            {
                "fields": {
                    FIELDS["nombre"]: nombre,
                    FIELDS["telefono"]: telefono
                }
            }
        ]
    }
    response = requests.post(AIRTABLE_URL, headers=AIRTABLE_HEADERS, json=datos_cliente)
    
    if response.status_code in [200, 201]:
        return response.json()["records"][0]["id"]  # Devuelve el ID del cliente
    return None

# Función para registrar cita en Airtable
def registrar_cita_airtable(nombre, telefono, fecha, hora, interes):
    cliente_id = buscar_cliente_telefono(telefono)

    if not cliente_id:  # Si el cliente no existe, lo registramos primero
        cliente_id = registrar_cliente_airtable(nombre, telefono)
        if not cliente_id:
            return False, "⚠️ No se pudo registrar al paciente en Airtable."

    datos_cita = {
        "records": [
            {
                "fields": {
                    FIELDS["nombre"]: [cliente_id],  # Relaciona la cita con el cliente
                    FIELDS["fecha"]: fecha,  
                    FIELDS["hora"]: hora,  
                    FIELDS["interes"]: interes,  
                    FIELDS["estado"]: "Programada",  
                    FIELDS["notas"]: f"Interesado en {interes} - Agendado por Gabriel (IA)"
                }
            }
        ]
    }
    response = requests.post(AIRTABLE_URL, headers=AIRTABLE_HEADERS, json=datos_cita)
    
    if response.status_code in [200, 201]:
        return True, "✅ Tu cita ha sido registrada en nuestra agenda."
    return False, f"⚠️ No se pudo registrar la cita: {response.text}"

# Función para obtener respuesta de OpenAI (GPT-4) con tono corporativo
def obtener_respuesta_ia(mensaje):
    prompt = f"""
    Eres Gabriel, el asistente virtual de Sonrisas Hollywood y Albane Clinic. 
    Tu misión es responder de manera profesional, clara y concisa. 
    Proporciona información sobre tratamientos dentales, estética facial y promociones.
    
    Si el usuario pregunta sobre tratamientos, responde con detalles.
    Si el usuario pregunta por precios, da una respuesta transparente con las tarifas actuales.
    Si el usuario quiere agendar una cita, guía el proceso de manera amigable.

    Usuario: {mensaje}
    Gabriel:
    """
    respuesta = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "system", "content": prompt}],
        max_tokens=150
    )
    return respuesta["choices"][0]["message"]["content"]

# Webhook para recibir mensajes de WhatsApp
@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip().lower()
    sender = request.values.get("From", "")

    resp = MessagingResponse()
    msg = resp.message()

    estado_usuario = redis_client.get(sender + "_estado") or ""

    if "cita" in incoming_msg or "agenda" in incoming_msg:
        redis_client.set(sender + "_estado", "esperando_nombre", ex=600)
        respuesta = "¡Hola! 😊 Para agendar una cita, dime tu nombre completo."

    elif estado_usuario == "esperando_nombre":
        redis_client.set(sender + "_nombre", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_telefono", ex=600)
        respuesta = f"Gracias, {incoming_msg}. Ahora dime tu número de teléfono 📞."

    elif estado_usuario == "esperando_telefono":
        redis_client.set(sender + "_telefono", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_fecha", ex=600)
        respuesta = "¡Perfecto! Ahora dime qué fecha prefieres (Ejemplo: '12/02/2025') 📅."

    elif estado_usuario == "esperando_fecha":
        redis_client.set(sender + "_fecha", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_hora", ex=600)
        respuesta = "Genial. ¿A qué hora te gustaría la cita? (Ejemplo: '16:00') ⏰"

    elif estado_usuario == "esperando_hora":
        redis_client.set(sender + "_hora", incoming_msg, ex=600)
        redis_client.set(sender + "_estado", "esperando_interes", ex=600)
        respuesta = "¿Qué tratamiento te interesa? (Ejemplo: 'Botox, diseño de sonrisa, ortodoncia') 😊."

    elif estado_usuario == "esperando_interes":
        nombre = redis_client.get(sender + "_nombre")
        telefono = redis_client.get(sender + "_telefono")
        fecha = redis_client.get(sender + "_fecha")
        hora = redis_client.get(sender + "_hora")
        interes = incoming_msg

        exito, mensaje = registrar_cita_airtable(nombre, telefono, fecha, hora, interes)
        respuesta = mensaje
        redis_client.delete(sender + "_estado")

    else:
        respuesta = obtener_respuesta_ia(incoming_msg)

    msg.body(respuesta)
    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
