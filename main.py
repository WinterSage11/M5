import os
import streamlit as st
from io import BytesIO
from openai import OpenAI
from dotenv import load_dotenv

# Prompt del proyecto (lo adaptaremos luego con base en tu prompts.py)
from prompts import stronger_prompt

# Tools + dispatcher (nuestro tooling.py)
from tooling import handle_tool_calls, tools

load_dotenv(override=True)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client_openai = OpenAI(api_key=OPENAI_API_KEY)

# Puedes cambiar el modelo aquí (ej: "gpt-5-mini" si lo deseas)
model_openai = "gpt-5.1"
model_transcribe = "whisper-1"
model_tts = "gpt-4o-mini-tts"


def stream_assistant_answer(client, model, conversation):
    """
    Igual que tu implementación: hace una segunda llamada con stream=True para pintar progresivamente.
    """
    full_response = ""
    placeholder = st.empty()

    stream = client.chat.completions.create(
        model=model,
        messages=conversation,
        stream=True,
    )

    for chunk in stream:
        delta = chunk.choices[0].delta
        if delta and delta.content:
            full_response += delta.content
            placeholder.markdown(full_response)

    return full_response


# ============================================================
# UI
# ============================================================

st.title("⚽ LineupAI (FantasyPL)")
st.caption("Comparativa de jugadores para una jornada (GW) usando datos oficiales de FPL.")

if "messages" not in st.session_state:
    st.session_state["messages"] = [
        {
            "role": "assistant",
            "content": (
                "¿Qué quieres comparar? Ejemplos:\n"
                "- 'Compara a Haaland vs Watkins para el próximo GW'\n"
                "- 'Tengo hasta 5.0m, ¿qué delanteros me convienen para el próximo GW?'\n"
                "- 'Explica xGI en lenguaje sencillo'"
            ),
        }
    ]

chat_container = st.container()
with chat_container:
    for msg in st.session_state.messages:
        message_block = st.chat_message(msg["role"])
        message_block.write(msg["content"])
        audio_payload = msg.get("audio")
        if audio_payload:
            message_block.audio(audio_payload, format="audio/mp3")


# Sidebar de audio (opcional) - idéntico a tu flujo :contentReference[oaicite:1]{index=1}
with st.sidebar:
    st.subheader("Entrada de audio (opcional)")
    audio_value = st.audio_input("Graba un mensaje de voz")
    send_audio = st.button("Enviar audio", key="send_audio_button", use_container_width=True)
    st.divider()
    st.subheader("Preferencias (local)")
    # Estos campos NO son tools: solo ayudan al usuario a especificar
    default_budget = st.number_input("Presupuesto máximo por jugador (£m)", min_value=0.0, value=0.0, step=0.1)
    st.caption("Si lo dejas en 0, se interpreta como 'sin presupuesto'.")


user_prompt = None
user_display_content = None

# Entrada texto o audio
if text_prompt := st.chat_input(placeholder="Escribe tu mensaje aquí..."):
    user_prompt = text_prompt
    user_display_content = text_prompt
elif send_audio:
    raw_audio = None
    filename = None
    source = None

    if audio_value is not None:
        raw_audio = audio_value.getvalue()
        filename = audio_value.name or "voz_usuario.wav"
        source = "Audio grabado"

    if raw_audio:
        audio_file = BytesIO(raw_audio)
        audio_file.name = filename or "voz_usuario.wav"
        with st.spinner("Transcribiendo audio..."):
            transcription = client_openai.audio.transcriptions.create(
                model=model_transcribe,
                file=audio_file,
            )
        user_prompt = (transcription.text or "").strip()
        if user_prompt:
            user_display_content = f"({source}) {user_prompt}" if source else user_prompt
        else:
            st.info("La transcripción no contiene texto interpretable. Intenta nuevamente.")
    else:
        st.warning("Graba un mensaje de voz antes de enviarlo.")


# Si hay presupuesto default, lo “inyectamos” como contexto suave
# (No obliga, solo ayuda al LLM a llamar tools con budget_million)
if user_prompt and default_budget and float(default_budget) > 0:
    user_prompt = f"{user_prompt}\n\n[Preferencia del usuario: presupuesto máximo por jugador = {float(default_budget):.1f} millones £]"


if user_prompt:
    st.session_state.messages.append({"role": "user", "content": user_prompt})
    st.chat_message("user").write(user_display_content or user_prompt)

    # Conversación para el modelo: prompt fuerte + historial
    conversation = [{"role": "assistant", "content": stronger_prompt}]
    conversation.extend({"role": m["role"], "content": m["content"]} for m in st.session_state.messages)

    # Loop de tool-calls (idéntico a tu main) :contentReference[oaicite:2]{index=2}
    done = False
    while not done:
        completion = client_openai.chat.completions.create(
            model=model_openai,
            messages=conversation,
            tools=tools,
        )
        choice = completion.choices[0]
        message = choice.message
        finish_reason = choice.finish_reason

        if finish_reason == "tool_calls" and message.tool_calls:
            tool_calls = message.tool_calls

            # Serialización para meterlo de regreso al conversation
            tool_calls_serialized = [
                {
                    "id": tc.id,
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    "type": tc.type,
                }
                for tc in tool_calls
            ]

            # Ejecutar tools via dispatcher
            results = handle_tool_calls(tool_calls)

            safe_content = message.content or ""
            if safe_content:
                st.session_state.messages.append({"role": message.role, "content": safe_content})

            conversation.append(
                {"role": message.role, "content": safe_content, "tool_calls": tool_calls_serialized}
            )
            conversation.extend(results)
            continue

        # Cuando ya no hay tools, paramos y hacemos streaming final
        done = True

    # Streaming final
    with st.chat_message("assistant"):
        response = stream_assistant_answer(client_openai, model_openai, conversation)

    st.session_state.messages.append({"role": "assistant", "content": response})

    # TTS opcional (idéntico a tu main) :contentReference[oaicite:3]{index=3}
    audio_bytes = None
    with st.spinner("Generando respuesta en audio..."):
        try:
            speech = client_openai.audio.speech.create(
                model=model_tts,
                voice="ash",
                input=response
            )
            audio_bytes = speech.read()
            if not audio_bytes:
                st.info("No se pudo obtener audio para esta respuesta.")
        except Exception as exc:
            st.error(f"No se pudo generar la voz sintética: {exc}")

    if audio_bytes:
        st.audio(audio_bytes, format="audio/mp3", autoplay=True)
        # guardar audio en el último mensaje
        last_message = st.session_state.messages[-1]
        if last_message["role"] == "assistant":
            last_message["audio"] = audio_bytes
