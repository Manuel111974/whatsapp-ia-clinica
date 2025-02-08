from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse
import openai
import os
import requests
import logging

app = Flask(__name__)

# Configuración de logs
logging.basicConfig(level=logging.DEBUG)

# API Keys desde Environment Variables en Render
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # Cambia la clave en Render si es necesario
KOIBOX_API_KEY = os.getenv("KOIBOX_API_KEY")  # Asegúrate de que está bien configurada

# Configurar OpenAI
openai.api_key = OPENAI_API_KEY

# 📌 Ofertas actuales de Sonrisas Hollywood
