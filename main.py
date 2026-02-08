import os
from dotenv import load_dotenv
import streamlit as st
from openai import OpenAI

load_dotenv(override=True)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client_openai = OpenAI(api_key=OPENAI_API_KEY)
model_openai = "gpt-5-mini"

st.set_page_config(page_title="FantasyPL Chatbot", layout="wide")
st.title("FantasyPL Chatbot 🤖 ⚽")
st.caption("¿Ya tienes tu alineación para esta semana?")

if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "¿En qué te puedo ayudar?"}]

for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

if prompt:= st.chat_input("Escribe tu mensaje aquí..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.chat_message("user").write(prompt)
    conversation = [{"role": "assistant", "content": "Eres un asistente de IA que ayuda a los usuarios a crear su alineación de Fantasy Premier League. Responde siempre en español."}]
    conversation.extend({"role": m["role"], "content": m["content"]} for m in st.session_state.messages)
    
    with st.chat_message("assistant"):
        stream = client_openai.chat.completions.create(model=model_openai, messages=conversation, stream=True)
        response = st.write_stream(stream)
    
    st.session_state.messages.append({"role": "assistant", "content": response})