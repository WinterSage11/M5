# tooling.py
import json

# Cuando exista utils_fpl.py, descomenta estos imports:
# from utils_fpl import (
#     search_player,
#     get_gw_context,
#     get_player_card,
#     compare_players,
#     explain_metric,
#     model_pick_players
# )

# ============================================================
# Tools JSON Schemas
# ============================================================

search_player_json = {
    "name": "search_player",
    "description": (
        "Encuentra jugadores de FPL por nombre o término de búsqueda y devuelve candidatos con player_id "
        "(element id). Útil porque el usuario no conoce IDs."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Texto de búsqueda. Ej: 'Salah', 'Haaland'."},
            "position": {"type": "string", "enum": ["GK", "DEF", "MID", "FWD"], "description": "Filtro opcional por posición."},
            "team": {"type": "string", "description": "Filtro opcional por equipo (nombre o abreviación)."},
            "budget_million": {
                "type": "number",
                "description": "Presupuesto máximo por jugador en millones (£). Ej: 5.0."
            },
            "limit": {
                "type": "integer",
                "description": "Máximo de candidatos a devolver (si se omite, el backend puede usar un default)."
            }
        },
        "required": ["query"],
        "additionalProperties": False
    }
}

get_gw_context_json = {
    "name": "get_gw_context",
    "description": "Obtiene contexto del Gameweek (GW): GW actual/próximo, deadlines, estado del evento, etc.",
    "parameters": {
        "type": "object",
        "properties": {"gw": {"type": "integer", "description": "GW objetivo. Si se omite, se infiere."}},
        "required": [],
        "additionalProperties": False
    }
}

get_player_card_json = {
    "name": "get_player_card",
    "description": (
        "Obtiene un snapshot de un jugador para un GW: forma reciente, minutos, métricas clave, "
        "fixture(s) del GW y alertas (sin bloquear)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "player_id": {"type": "integer", "description": "ID del jugador en FPL (element id)."},
            "gw": {"type": "integer", "description": "GW objetivo."},
            "window": {"type": "integer", "description": "Ventana de forma (últimos N GWs)."},
            "budget_million": {"type": "number", "description": "Presupuesto máximo por jugador en millones (£)."}
        },
        "required": ["player_id", "gw"],
        "additionalProperties": False
    }
}

compare_players_json = {
    "name": "compare_players",
    "description": (
        "Compara 2 a 5 jugadores para un GW específico. Importante: NO decide; "
        "solo entrega métricas comparables, alertas y lectura interpretativa."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "player_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 2,
                "maxItems": 5,
                "description": "Lista de player_id a comparar (2 a 5)."
            },
            "gw": {"type": "integer", "description": "GW objetivo."},
            "window": {"type": "integer", "description": "Ventana de forma (últimos N GWs)."},
            "budget_million": {
                "type": "number",
                "description": "Presupuesto máximo por jugador en millones (£). Se marcarán jugadores fuera de presupuesto."
            }
        },
        "required": ["player_ids", "gw"],
        "additionalProperties": False
    }
}

explain_metric_json = {
    "name": "explain_metric",
    "description": "Explica una métrica FPL (xG, xA, xGI, ICT, BPS, etc.) en formato humano y cómo interpretarla.",
    "parameters": {
        "type": "object",
        "properties": {"metric": {"type": "string", "description": "Métrica a explicar. Ej: 'xG', 'ICT'."}},
        "required": ["metric"],
        "additionalProperties": False
    }
}

model_pick_players_json = {
    "name": "model_pick_players",
    "description": (
        "SOLO para elección basada en modelo: predice total_points del próximo GW. "
        "Dos modos: (1) 'list' rankea una lista de 2 a 5 player_ids; (2) 'pool' rankea un conjunto filtrado "
        "por posición y presupuesto. Si el modelo no está disponible, devuelve 'not_available' sin inventar."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["list", "pool"],
                "description": "Modo: 'list' para IDs; 'pool' para buscar candidatos filtrados."
            },
            "player_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 2,
                "maxItems": 5,
                "description": "Solo en mode='list': player_ids a evaluar."
            },
            "position": {
                "type": "string",
                "enum": ["GK", "DEF", "MID", "FWD"],
                "description": "Solo en mode='pool': filtra por posición."
            },
            "team": {"type": "string", "description": "Solo en mode='pool': filtro opcional por equipo."},
            "gw": {"type": "integer", "description": "GW objetivo (próximo GW a predecir)."},
            "budget_million": {
                "type": "number",
                "description": "Presupuesto máximo por jugador en millones (£)."
            },
            "limit": {
                "type": "integer",
                "description": "Solo en mode='pool': cuántas opciones devolver. Si se omite, usaremos default=10."
            }
        },
        "required": ["mode", "gw"],
        "additionalProperties": False
        # Nota: validación estricta (if/then) se puede hacer en backend si lo prefieres.
    }
}

# ============================================================
# Tools list (OpenAI function calling format)
# ============================================================

tools = [
    {"type": "function", "function": search_player_json},
    {"type": "function", "function": get_gw_context_json},
    {"type": "function", "function": get_player_card_json},
    {"type": "function", "function": compare_players_json},
    {"type": "function", "function": explain_metric_json},
    {"type": "function", "function": model_pick_players_json},
]

# ============================================================
# Dispatcher
# ============================================================

DEFAULT_POOL_LIMIT = 10

def _apply_defaults(tool_name: str, arguments: dict) -> dict:
    """
    Inserta defaults sin obligar al usuario a especificarlos.
    Importante: NO inventa parámetros críticos como budget_million si no vienen.
    """
    if tool_name == "model_pick_players":
        mode = arguments.get("mode")
        if mode == "pool":
            # Default limit si no viene
            if arguments.get("limit") is None:
                arguments["limit"] = DEFAULT_POOL_LIMIT
    return arguments


def handle_tool_calls(tool_calls):
    """
    - Parsea args
    - Aplica defaults (ej. limit=10 en model_pick_players pool)
    - Llama a la función homónima si existe en globals()
    - Devuelve mensajes role=tool
    """
    results = []
    for tool_call in tool_calls:
        tool_name = tool_call.function.name
        arguments = json.loads(tool_call.function.arguments or "{}")
        arguments = _apply_defaults(tool_name, arguments)

        print(f"Tool called: {tool_name}", flush=True)

        tool_fn = globals().get(tool_name)

        if not tool_fn:
            result = {
                "status": "error",
                "tool": tool_name,
                "message": (
                    f"La tool '{tool_name}' está registrada, pero la función no está implementada/importada aún."
                )
            }
        else:
            try:
                result = tool_fn(**arguments)
            except Exception as e:
                result = {"status": "error", "tool": tool_name, "message": str(e)}

        results.append({
            "role": "tool",
            "content": json.dumps(result),
            "tool_call_id": tool_call.id
        })

    return results
