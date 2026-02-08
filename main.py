import os
from dotenv import load_dotenv
import streamlit as st
from openai import OpenAI

load_dotenv(override=True)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

st.set_page_config(page_title="FantasyPL Chatbot", layout="wide")
st.title("FantasyPL Chatbot 🤖 ⚽")
st.caption("¿Ya tienes tu alineación para esta semana?")

prompt = st.text_input("¿En qué te puedo ayudar?")
if prompt:
    st.write(f"El usuario ha enviado el siguiente propmpt: {prompt}")
