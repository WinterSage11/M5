# utils_fpl.py
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests


FPL_BOOTSTRAP = "https://fantasy.premierleague.com/api/bootstrap-static/"
FPL_PLAYER_SUMMARY = "https://fantasy.premierleague.com/api/element-summary/{player_id}/"


# ============================================================
# Simple in-memory cache (suficiente para Streamlit)
# ============================================================

_CACHE: Dict[str, Tuple[float, Any]] = {}  # key -> (timestamp, payload)


def _cache_get(key: str, ttl_seconds: int) -> Optional[Any]:
    hit = _CACHE.get(key)
    if not hit:
        return None
    ts, payload = hit
    if (time.time() - ts) > ttl_seconds:
        return None
    return payload


def _cache_set(key: str, payload: Any) -> None:
    _CACHE[key] = (time.time(), payload)


# ============================================================
# HTTP session with basic robustness
# ============================================================

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": "FantasyPL-Assistant/1.0 (+streamlit)"
})


def _get_json(url: str, ttl_seconds: int = 300) -> Dict[str, Any]:
    """
    GET JSON with in-memory caching.
    """
    cached = _cache_get(url, ttl_seconds=ttl_seconds)
    if cached is not None:
        return cached

    resp = _SESSION.get(url, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    _cache_set(url, data)
    return data


# ============================================================
# Fetchers (fuentes de verdad)
# ============================================================

def fetch_bootstrap_static(ttl_seconds: int = 300) -> Dict[str, Any]:
    return _get_json(FPL_BOOTSTRAP, ttl_seconds=ttl_seconds)


def fetch_element_summary(player_id: int, ttl_seconds: int = 300) -> Dict[str, Any]:
    url = FPL_PLAYER_SUMMARY.format(player_id=int(player_id))
    return _get_json(url, ttl_seconds=ttl_seconds)


# ============================================================
# Core helpers
# ============================================================

def get_current_or_next_gw(bootstrap: Dict[str, Any]) -> int:
    """
    Devuelve GW actual o próximo basado en bootstrap['events'].
    - Si hay uno 'is_current' úsalo.
    - Si no, usa el próximo 'is_next'.
    """
    events = bootstrap.get("events", [])
    for ev in events:
        if ev.get("is_current"):
            return int(ev["id"])
    for ev in events:
        if ev.get("is_next"):
            return int(ev["id"])
    # fallback: el mayor id
    return int(max((e.get("id", 1) for e in events), default=1))


def _team_map(bootstrap: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    return {int(t["id"]): t for t in bootstrap.get("teams", [])}


def _position_map(bootstrap: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    return {int(p["id"]): p for p in bootstrap.get("element_types", [])}


def _players(bootstrap: Dict[str, Any]) -> List[Dict[str, Any]]:
    return bootstrap.get("elements", [])


def _normalize_team_name(team_obj: Dict[str, Any]) -> str:
    # FPL teams trae 'short_name' y 'name'
    return team_obj.get("short_name") or team_obj.get("name") or ""


def _matches_team_filter(team_obj: Dict[str, Any], team_filter: str) -> bool:
    if not team_filter:
        return True
    tf = team_filter.strip().lower()
    return (
        tf in (team_obj.get("short_name", "").lower())
        or tf in (team_obj.get("name", "").lower())
    )


def _position_id_from_code(code: str) -> Optional[int]:
    # FPL element_type: 1=GK,2=DEF,3=MID,4=FWD
    mapping = {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}
    return mapping.get(code)


# ============================================================
# TOOL FUNCTIONS (deben matchear nombres en tooling.py)
# ============================================================

def search_player(
    query: str,
    position: Optional[str] = None,
    team: Optional[str] = None,
    budget_million: Optional[float] = None,
    limit: Optional[int] = None
) -> Dict[str, Any]:
    """
    Busca jugadores por nombre (web_name / first_name / second_name).
    Devuelve candidatos con player_id para que otras tools trabajen.
    """
    try:
        bootstrap = fetch_bootstrap_static()
        teams = _team_map(bootstrap)
        positions = _position_map(bootstrap)

        q = (query or "").strip().lower()
        if not q:
            return {"status": "error", "message": "query vacío"}

        pos_id = _position_id_from_code(position) if position else None
        lim = int(limit) if limit else 10

        candidates = []
        for p in _players(bootstrap):
            name_blob = " ".join([
                str(p.get("web_name", "")),
                str(p.get("first_name", "")),
                str(p.get("second_name", "")),
            ]).lower()

            if q not in name_blob:
                continue

            if pos_id and int(p.get("element_type")) != pos_id:
                continue

            team_obj = teams.get(int(p.get("team")))
            if team and team_obj and (not _matches_team_filter(team_obj, team)):
                continue

            # now_cost viene en décimas (ej 75 => £7.5m)
            price_m = float(p.get("now_cost", 0)) / 10.0
            if budget_million is not None and price_m > float(budget_million):
                continue

            candidates.append({
                "player_id": int(p["id"]),
                "web_name": p.get("web_name"),
                "team": _normalize_team_name(team_obj or {}),
                "position": positions.get(int(p.get("element_type", 0)), {}).get("singular_name_short"),
                "now_cost_million": price_m,
                "status": p.get("status"),
                "chance_next_round": p.get("chance_of_playing_next_round"),
                "selected_by_percent": p.get("selected_by_percent"),
                "total_points": p.get("total_points"),
            })

        # Orden simple: más puntos totales y luego más seleccionado
        def _safe_float(x):
            try:
                return float(x)
            except Exception:
                return 0.0

        candidates.sort(
            key=lambda r: (_safe_float(r.get("total_points")), _safe_float(r.get("selected_by_percent"))),
            reverse=True
        )

        return {
            "status": "ok",
            "query": query,
            "count": len(candidates[:lim]),
            "results": candidates[:lim]
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_gw_context(gw: Optional[int] = None) -> Dict[str, Any]:
    """
    Contexto GW basado en bootstrap events.
    """
    try:
        bootstrap = fetch_bootstrap_static()
        events = bootstrap.get("events", [])
        if not events:
            return {"status": "error", "message": "No events en bootstrap"}

        if gw is None:
            gw = get_current_or_next_gw(bootstrap)

        ev = next((e for e in events if int(e.get("id")) == int(gw)), None)
        if not ev:
            return {"status": "error", "message": f"GW {gw} no encontrado en events"}

        return {
            "status": "ok",
            "gw": int(gw),
            "is_current": bool(ev.get("is_current")),
            "is_next": bool(ev.get("is_next")),
            "deadline_time": ev.get("deadline_time"),
            "finished": bool(ev.get("finished")),
            "data_checked": bool(ev.get("data_checked")),
            "highest_score": ev.get("highest_score"),
            "average_entry_score": ev.get("average_entry_score"),
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_player_card(
    player_id: int,
    gw: int,
    window: Optional[int] = 5,
    budget_million: Optional[float] = None
) -> Dict[str, Any]:
    """
    Snapshot de jugador para GW:
    - Identity + costo + status
    - Forma simple (últimos window GWs) -> placeholder (lo afinamos después)
    - Fixture(s) del GW -> desde element-summary
    - Alertas -> status/chance/news
    """
    try:
        bootstrap = fetch_bootstrap_static()
        teams = _team_map(bootstrap)
        positions = _position_map(bootstrap)

        # player row
        player = next((p for p in _players(bootstrap) if int(p["id"]) == int(player_id)), None)
        if not player:
            return {"status": "error", "message": f"player_id {player_id} no encontrado en bootstrap"}

        summary = fetch_element_summary(int(player_id))

        team_obj = teams.get(int(player.get("team")))
        position_obj = positions.get(int(player.get("element_type", 0)), {})

        price_m = float(player.get("now_cost", 0)) / 10.0
        out_of_budget = (budget_million is not None and price_m > float(budget_million))

        alerts = []
        status = player.get("status")
        chance = player.get("chance_of_playing_next_round")
        news = player.get("news")

        if status and status != "a":
            alerts.append(f"status='{status}'")
        if chance is not None and chance != 100:
            alerts.append(f"chance_of_playing_next_round={chance}")
        if news:
            alerts.append("news disponible")

        # Fixtures del GW (element-summary fixtures)
        fixtures = summary.get("fixtures", [])
        gw_fixtures = [f for f in fixtures if int(f.get("event", -1)) == int(gw)]

        # Forma básica placeholder: últimos N registros de history
        hist = summary.get("history", [])
        hist_sorted = sorted(hist, key=lambda r: int(r.get("round", 0)))
        last_n = hist_sorted[-int(window):] if hist_sorted else []

        form = {
            "window": int(window),
            "matches": len(last_n),
            "points_last_n": sum(int(r.get("total_points", 0)) for r in last_n) if last_n else 0,
            "minutes_last_n": sum(int(r.get("minutes", 0)) for r in last_n) if last_n else 0,
            # placeholders para xG/xA/xGI si vienen en history:
            "xG_last_n": sum(float(r.get("expected_goals", 0) or 0) for r in last_n) if last_n else None,
            "xA_last_n": sum(float(r.get("expected_assists", 0) or 0) for r in last_n) if last_n else None,
        }

        return {
            "status": "ok",
            "player": {
                "player_id": int(player_id),
                "web_name": player.get("web_name"),
                "team": _normalize_team_name(team_obj or {}),
                "position": position_obj.get("singular_name_short"),
                "now_cost_million": price_m,
                "out_of_budget": bool(out_of_budget),
                "status": status,
                "chance_next_round": chance,
                "news": news,
            },
            "gw": int(gw),
            "alerts": alerts,
            "form": form,
            "gw_fixtures": gw_fixtures,  # lo dejamos “raw” por ahora para no perder campos
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


def compare_players(
    player_ids: List[int],
    gw: int,
    window: Optional[int] = 5,
    budget_million: Optional[float] = None
) -> Dict[str, Any]:
    """
    Comparación descriptiva (NO decide):
    devuelve cards + una tabla comparativa simple.
    """
    try:
        if not (2 <= len(player_ids) <= 5):
            return {"status": "error", "message": "player_ids debe tener entre 2 y 5 elementos"}

        cards = []
        for pid in player_ids:
            cards.append(get_player_card(int(pid), int(gw), window=window, budget_million=budget_million))

        # Si alguna card falla, devolvemos igual todo, pero marcamos errores
        ok_cards = [c for c in cards if c.get("status") == "ok"]

        table = []
        for c in ok_cards:
            p = c["player"]
            f = c["form"]
            table.append({
                "player_id": p["player_id"],
                "name": p["web_name"],
                "team": p["team"],
                "pos": p["position"],
                "price_m": p["now_cost_million"],
                "out_of_budget": p["out_of_budget"],
                "alerts_n": len(c.get("alerts", [])),
                "points_last_n": f.get("points_last_n"),
                "minutes_last_n": f.get("minutes_last_n"),
                "xG_last_n": f.get("xG_last_n"),
                "xA_last_n": f.get("xA_last_n"),
                "fixtures_in_gw": len(c.get("gw_fixtures", [])),
            })

        return {
            "status": "ok",
            "gw": int(gw),
            "window": int(window),
            "budget_million": budget_million,
            "cards": cards,    # incluye errores si los hay
            "table": table
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


def explain_metric(metric: str) -> Dict[str, Any]:
    """
    Explicación humana de métricas (mínimo viable).
    Luego lo conectamos a prompts.py si quieres consistencia.
    """
    m = (metric or "").strip().lower()
    explanations = {
        "xg": "xG (expected goals): goles esperados según la calidad de las oportunidades; mide amenaza de gol.",
        "xa": "xA (expected assists): asistencias esperadas según la calidad de los pases que generan tiro.",
        "xgi": "xGI (expected goal involvement): xG + xA; participación esperada en goles.",
        "ict": "ICT Index: métrica compuesta de FPL (Influence, Creativity, Threat) para resumir impacto ofensivo.",
        "bps": "BPS (Bonus Points System): puntos base usados para asignar bonus; depende de acciones en partido.",
        "minutes": "Minutes: minutos jugados; útil para estimar probabilidad de titularidad y retorno de puntos.",
        "form": "Form: indicador de rendimiento reciente; normalmente relacionado a puntos recientes.",
    }
    text = explanations.get(m, f"No tengo una explicación predefinida para '{metric}'.")
    return {"status": "ok", "metric": metric, "explanation": text}


def model_pick_players(
    mode: str,
    gw: int,
    player_ids: Optional[List[int]] = None,
    position: Optional[str] = None,
    team: Optional[str] = None,
    budget_million: Optional[float] = None,
    limit: Optional[int] = None
) -> Dict[str, Any]:
    """
    Placeholder: aquí irá el modelo.
    Por ahora devolvemos not_available de forma explícita (sin inventar).
    """
    return {
        "status": "not_available",
        "message": "El modelo aún no está implementado. Usa compare_players para comparación descriptiva.",
        "requested": {
            "mode": mode,
            "gw": gw,
            "player_ids": player_ids,
            "position": position,
            "team": team,
            "budget_million": budget_million,
            "limit": limit,
        }
    }