from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import openai
import requests

app = Flask(__name__)

# 🔹 Configuración de Twilio
import os

account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")
openai_api_key = os.getenv("OPENAI_API_KEY")

# 🔹 API Key de OpenAI
import os
openai.api_key = os.getenv("OPENAI_API_KEY")

@app.route("/webhook", methods=["POST"])
def whatsapp_reply():
    incoming_msg = request.form.get("Body", "").strip().lower()
    sender_number = request.form.get("From")

    print(f"📩 Mensaje recibido de {sender_number}: {incoming_msg}")

    resp = MessagingResponse()
    msg = resp.message()

    # 🔹 Generar respuesta con OpenAI
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "system", "content": "Eres un asistente para una clínica dental y estética."},
                      {"role": "user", "content": incoming_msg}]
        )
        respuesta_ia = response["choices"][0]["message"]["content"].strip()
        msg.body(respuesta_ia)
    except Exception as e:
        msg.body("Lo siento, no puedo responder en este momento.")

    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
