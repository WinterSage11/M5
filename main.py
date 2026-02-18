import os
import streamlit as st
from io import BytesIO
from openai import OpenAI
from dotenv import load_dotenv

from prompts import stronger_prompt

# Tools + dispatcher
from tooling import handle_tool_calls, tools

load_dotenv(override=True)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client_openai = OpenAI(api_key=OPENAI_API_KEY)

# Puedes cambiar el modelo aquí (ej: "gpt-5-mini" si lo deseas)
model_openai = "gpt-5.1"
model_transcribe = "whisper-1"
model_tts = "gpt-4o-mini-tts"


def stream_assistant_answer(client, model, conversation):
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

# ==========================
# Page config + Theme CSS
# ==========================
st.set_page_config(
    page_title="LineupAI (FantasyPL)",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      /* Fondo general */
      .stApp {
        background: linear-gradient(135deg, #061833 0%, #0A2A5E 45%, #0B4AA1 100%);
      }

      /* Quitar fondo del header (barra superior) */
      [data-testid="stHeader"] {
        background: rgba(0,0,0,0);
      }

      /* Sidebar estilo glass */
      [data-testid="stSidebar"] {
        background: rgba(255,255,255,0.06);
        border-right: 1px solid rgba(255,255,255,0.10);
        backdrop-filter: blur(10px);
      }

      /* Contenedor principal */
      .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
      }

      /* Tarjetas para los mensajes del chat */
      [data-testid="stChatMessage"] {
        background: rgba(255,255,255,0.08);
        border: 1px solid rgba(255,255,255,0.12);
        border-radius: 18px;
        padding: 12px 14px;
        margin-bottom: 10px;
        box-shadow: 0 6px 18px rgba(0,0,0,0.18);
      }

      /* Tipografía legible en fondos oscuros */
      html, body, [class*="css"]  {
        color: rgba(255,255,255,0.92);
      }
      .stMarkdown, .stCaption, .stText, p, li {
        color: rgba(255,255,255,0.88) !important;
      }

      /* Botón principal con acento */
      button[kind="primary"] {
        background: #00D4FF !important;
        color: #001018 !important;
        border-radius: 14px !important;
        border: 0 !important;
        font-weight: 650 !important;
      }

      /* Inputs generales */
      [data-testid="stTextInput"] input,
      [data-testid="stNumberInput"] input {
        background: rgba(255,255,255,0.06) !important;
        border: 1px solid rgba(255,255,255,0.14) !important;
        border-radius: 12px !important;
        color: rgba(255,255,255,0.92) !important;
      }

      /* --- CHAT INPUT (donde escribe el usuario) EN AZUL --- */
      [data-testid="stChatInput"] textarea {
        background: rgba(0, 180, 255, 0.12) !important;   /* azul translúcido */
        border: 1px solid rgba(0, 212, 255, 0.35) !important;
        color: rgba(255,255,255,0.95) !important;
        border-radius: 14px !important;
        caret-color: #00D4FF !important;
      }

      /* A veces el negro viene del contenedor */
      [data-testid="stChatInput"] > div {
        background: transparent !important;
      }

      /* Placeholder */
      [data-testid="stChatInput"] textarea::placeholder {
        color: rgba(255,255,255,0.65) !important;
      }

      /* Plan B más agresivo (por si la versión de Streamlit insiste) */
      div[data-testid="stChatInput"] textarea,
      div[data-testid="stChatInput"] textarea:focus,
      div[data-testid="stChatInput"] textarea:active {
        background-color: rgba(0, 180, 255, 0.12) !important;
      }

      /* Separadores más sutiles */
      hr {
        border-top: 1px solid rgba(255,255,255,0.10);
      }

      /* ================================
   FIX: “frame” negro inferior
   (contenedor fijo del chat input)
   PON ESTO AL FINAL DEL <style>
   ================================ */

    /* El contenedor grande de la app (a veces el negro viene de aquí) */
    [data-testid="stAppViewContainer"] {
    background: linear-gradient(135deg, #061833 0%, #0A2A5E 45%, #0B4AA1 100%) !important;
    }

    /* En algunas versiones, el "suelo" del main es el que queda negro */
    [data-testid="stMain"] {
    background: transparent !important;
    }

    /* Contenedor inferior (MUY común en versiones recientes) */
    [data-testid="stBottomBlockContainer"] {
    background: rgba(6, 24, 51, 0.85) !important;          /* azul oscuro */
    border-top: 1px solid rgba(255,255,255,0.10) !important;
    backdrop-filter: blur(10px);
    }

    /* Variante alternativa del contenedor inferior */
    [data-testid="stBottom"] {
    background: rgba(6, 24, 51, 0.85) !important;
    border-top: 1px solid rgba(255,255,255,0.10) !important;
    backdrop-filter: blur(10px);
    }

    /* Si el negro es un wrapper/section alrededor */
    section[data-testid="stBottomBlockContainer"],
    section[data-testid="stBottom"] {
    background: rgba(6, 24, 51, 0.85) !important;
    }

    /* Asegurar que el chat input “card” se vea azul y no herede negro */
    [data-testid="stChatInput"] {
    background: rgba(255,255,255,0.06) !important;
    border: 1px solid rgba(255,255,255,0.10) !important;
    border-radius: 18px !important;
    padding: 12px 12px !important;
    box-shadow: 0 10px 24px rgba(0,0,0,0.18) !important;
    }

    /* Input azul */
    [data-testid="stChatInput"] textarea {
    background: rgba(0, 180, 255, 0.14) !important;
    border: 1px solid rgba(0, 212, 255, 0.35) !important;
    color: rgba(255,255,255,0.95) !important;
    border-radius: 14px !important;
    caret-color: #00D4FF !important;
    }

    /* Contenedor interno del input (evita “placa” negra) */
    [data-testid="stChatInput"] > div {
    background: transparent !important;
    }


 
    </style>
    """,
    unsafe_allow_html=True,
)

# ==========================
# Header "producto" (Opción 2)
# ==========================
st.markdown(
    """
    <div style="
      background: rgba(255,255,255,0.06);
      border: 1px solid rgba(255,255,255,0.12);
      border-radius: 22px;
      padding: 18px 18px;
      box-shadow: 0 10px 24px rgba(0,0,0,0.18);
      margin-bottom: 12px;
    ">
      <div style="font-size: 28px; font-weight: 800;">⚽ LineupAI <span style="opacity:0.8;">(FantasyPL)</span></div>
      <div style="margin-top:6px; font-size: 14px; opacity: 0.9;">
        Comparativa de jugadores para una jornada (GW) usando datos oficiales de FPL.
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)


if "messages" not in st.session_state:
    st.session_state["messages"] = [
        {
            "role": "assistant",
            "content": (
                "👋 **LineupAI (FantasyPL)** — comparo jugadores y busco opciones para el próximo GW con datos oficiales de FPL.\n\n"
                "🧭 **Cómo usar la app**\n"
                "- **Presupuesto (izquierda):** pon tu máximo por jugador (£m). Si lo dejas en **0.0**, es **sin límite**.\n\n"
                "✅ **Prueba con:**\n"
                "- \"Compara Haaland vs Watkins para el próximo GW\"\n"
                "- \"Tengo hasta 5.0m, ¿qué delanteros puedo escoger para el próximo GW?\"\n"
                "- \"Mejores porteros ≤ 5.0m\" / \"Top goleadores\" / \"Top asistidores\"\n"
                "- \"Explica xGI en sencillo\"\n\n"
                "📌 En tablas verás: **precio**, **status/chance**, **forma reciente**, **xGI**, y para defensivos: **CS/GC/BPS** (+ **saves** en GKP). "
                "Si el modelo está disponible, también verás **pred_total_points_next_gw**.\n\n"
                "¿Qué quieres hacer?"
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
