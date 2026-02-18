# utils_fpl.py
from __future__ import annotations
import joblib
import numpy as np
import pandas as pd
import json
import time
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path




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

def _safe_int(x, default=None):
    try:
        if x is None:
            return default
        return int(x)
    except Exception:
        return default

# ============================================================
# TOOL FUNCTIONS (deben matchear nombres en tooling.py)
# ============================================================



def _strip_accents(s: str) -> str:
    s = (s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))

def search_player(
    query: str,
    position: Optional[str] = None,
    team: Optional[str] = None,
    budget_million: Optional[float] = None,
    limit: Optional[int] = None
) -> Dict[str, Any]:
    """
    Busca jugadores por nombre (web_name / first_name / second_name).
    Soporta acentos (Sánchez == Sanchez).
    """
    try:
        bootstrap = fetch_bootstrap_static()
        teams = _team_map(bootstrap)
        positions = _position_map(bootstrap)

        q_raw = (query or "").strip()
        q = _strip_accents(q_raw)
        match_all = (q in {"*", "all", "any"})
        if (not q) and (not match_all):
            return {"status": "error", "message": "query vacío. Usa query='*' para listar por filtros."}

        pos_id = _position_id_from_code(position) if position else None
        lim = int(limit) if limit is not None else 15

        candidates = []
        for p in _players(bootstrap):
            name_blob = " ".join([
                str(p.get("web_name", "")),
                str(p.get("first_name", "")),
                str(p.get("second_name", "")),
            ])
            name_blob_n = _strip_accents(name_blob)

            if (not match_all) and (q not in name_blob_n):
                continue

            if pos_id and int(p.get("element_type")) != pos_id:
                continue

            team_obj = teams.get(int(p.get("team")))
            if team and team_obj and (not _matches_team_filter(team_obj, team)):
                continue

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
        gw_fixtures = [f for f in fixtures if _safe_int(f.get("event"), default=-1) == int(gw)]


        # Forma básica placeholder: últimos N registros de history
        hist = summary.get("history", [])
        hist_sorted = sorted(hist, key=lambda r: _safe_int(r.get("round"), default=0) or 0)

        last_n = hist_sorted[-int(window):] if hist_sorted else []

                # Forma básica: últimos N registros de history
        hist = summary.get("history", [])
        hist_sorted = sorted(hist, key=lambda r: _safe_int(r.get("round"), default=0) or 0)
        last_n = hist_sorted[-int(window):] if hist_sorted else []

        points_last_n = sum(int(r.get("total_points", 0)) for r in last_n) if last_n else 0
        minutes_last_n = sum(int(r.get("minutes", 0)) for r in last_n) if last_n else 0

        xg_last_n = sum(float(r.get("expected_goals", 0) or 0) for r in last_n) if last_n else 0.0
        xa_last_n = sum(float(r.get("expected_assists", 0) or 0) for r in last_n) if last_n else 0.0
        xgi_last_n = xg_last_n + xa_last_n

        clean_sheets_last_n = sum(int(r.get("clean_sheets", 0) or 0) for r in last_n) if last_n else 0
        goals_conceded_last_n = sum(int(r.get("goals_conceded", 0) or 0) for r in last_n) if last_n else 0
        bps_last_n = sum(int(r.get("bps", 0) or 0) for r in last_n) if last_n else 0
        saves_last_n = sum(int(r.get("saves", 0) or 0) for r in last_n) if last_n else 0

        form = {
            "window": int(window),
            "matches": len(last_n),
            "points_last_n": points_last_n,
            "minutes_last_n": minutes_last_n,
            "xG_last_n": round(xg_last_n, 3),
            "xA_last_n": round(xa_last_n, 3),
            "xGI_last_n": round(xgi_last_n, 3),
            "clean_sheets_last_n": clean_sheets_last_n,
            "goals_conceded_last_n": goals_conceded_last_n,
            "bps_last_n": bps_last_n,
            "saves_last_n": saves_last_n,
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
    mode: Optional[str],
    gw: int,
    player_ids: Optional[List[int]] = None,
    position: Optional[str] = None,
    team: Optional[str] = None,
    budget_million: Optional[float] = None,
    limit: int = 15,
) -> Dict[str, Any]:

    # 0) Normalizar mode (blindaje)
    mode_raw = (mode or "").strip().lower()
    pool_aliases = {"pool", "rank", "ranking", "top", "list", "best", "recommend", "recomendar"}
    compare_aliases = {"compare", "vs", "versus", "duel"}

    if mode_raw in pool_aliases:
        mode_n = "pool"
    elif mode_raw in compare_aliases:
        mode_n = "compare"
    else:
        # fallback por señales
        mode_n = "compare" if player_ids else "pool"

    # 1) Cargar modelo (HGB)
    model, meta = load_ridge_model()   # <- CAMBIO IMPORTANTE
    if model is None or meta is None:
        return {
            "status": "not_available",
            "message": "No se encontró el modelo en ./artifacts/. Genera artifacts con el notebook y vuelve a intentar.",
            "requested": {
                "mode": mode_n, "gw": int(gw), "player_ids": player_ids,
                "position": position, "team": team,
                "budget_million": budget_million, "limit": int(limit)
            }
        }

    # 2) Compare mode
    if mode_n == "compare":
        if not player_ids:
            return {"status": "error", "message": "mode=compare requiere player_ids"}

        pred = predict_next_gw_points(player_ids=list(player_ids), gw=int(gw))
        if pred.get("status") != "ok":
            return pred

        return {
            "status": "ok",
            "mode": "compare",
            "gw": int(gw),
            "predictions": pred.get("predictions", []),
            "errors": pred.get("errors", {})
        }

    # 3) Pool mode
    # (si no es compare, tratamos como pool)
    if not position:
        return {"status": "error", "message": "mode=pool requiere position"}

    pool = pool_players_descriptive(
        position=position,
        budget_million=float(budget_million) if budget_million is not None else 999.0,
        gw=int(gw),
        window=int(meta.get("window", 5)),
        limit=int(limit),
        team=team
    )
    if pool.get("status") != "ok":
        return pool

    pool_rows = pool.get("table", []) or []
    pool_ids = [r.get("player_id") for r in pool_rows if r.get("player_id") is not None]

    if not pool_ids:
        return {
            "status": "ok",
            "mode": "pool",
            "gw": int(gw),
            "position": position,
            "budget_million": budget_million,
            "limit": int(limit),
            "table": [],
            "errors": {}
        }

    pred = predict_next_gw_points(player_ids=pool_ids, gw=int(gw))
    if pred.get("status") != "ok":
        return pred

    pred_map = {p["player_id"]: p.get("pred_total_points_next_gw") for p in pred.get("predictions", [])}

    # Enriquecer tabla + ordenar
    table = []
    for r in pool_rows:
        pid = r.get("player_id")
        r2 = dict(r)
        r2["pred_total_points_next_gw"] = pred_map.get(pid)
        table.append(r2)

    table.sort(
        key=lambda x: (x.get("pred_total_points_next_gw") is not None, x.get("pred_total_points_next_gw", -1e9)),
        reverse=True
    )

    return {
        "status": "ok",
        "mode": "pool",
        "gw": int(gw),
        "position": position,
        "budget_million": budget_million,
        "limit": int(limit),
        "table": table,
        "errors": pred.get("errors", {})
    }



def pool_players_descriptive(
    position: str,
    budget_million: float,
    gw: int,
    window: int = 5,
    limit: int = 15,
    team: Optional[str] = None
) -> Dict[str, Any]:
    """
    Pool descriptivo enriquecido:
    - Filtra por posición + presupuesto (y equipo opcional)
    - Devuelve tabla con métricas estándar para decisión (sin recomendar).
    """
    try:
        # 1) Buscar candidatos por filtros usando query="*"
        base = search_player(
            query="*",
            position=position,
            team=team,
            budget_million=budget_million,
            limit=limit
        )
        if base.get("status") != "ok":
            return base

        results = base.get("results", [])
        if not results:
            return {
                "status": "ok",
                "gw": int(gw),
                "position": position,
                "budget_million": float(budget_million),
                "window": int(window),
                "limit": int(limit),
                "count": 0,
                "table": [],
                "cards": [],
            }

        # 2) Enriquecer con cards
        cards = []
        table = []

        # mapa posición id
        bootstrap = fetch_bootstrap_static()
        pos_id = _position_id_from_code(position)
        is_gk = (position == "GK")

        for r in results:
            pid = int(r["player_id"])
            c = get_player_card(pid, gw, window=window, budget_million=budget_million)
            cards.append(c)

            if c.get("status") != "ok":
                continue

            p = c["player"]
            f = c["form"]

            row = {
                "player_id": p["player_id"],
                "name": p["web_name"],
                "team": p["team"],
                "pos": p["position"],
                "price_m": p["now_cost_million"],
                "status": p["status"],
                "chance_next_round": p["chance_next_round"],
                "out_of_budget": p["out_of_budget"],
                "alerts_n": len(c.get("alerts", [])),
                "points_last_n": f.get("points_last_n"),
                "minutes_last_n": f.get("minutes_last_n"),
                "xGI_last_n": f.get("xGI_last_n"),
                "clean_sheets_last_n": f.get("clean_sheets_last_n"),
                "goals_conceded_last_n": f.get("goals_conceded_last_n"),
                "bps_last_n": f.get("bps_last_n"),
            }

            if is_gk:
                row["saves_last_n"] = f.get("saves_last_n")

            table.append(row)

        return {
            "status": "ok",
            "gw": int(gw),
            "position": position,
            "team_filter": team,
            "budget_million": float(budget_million),
            "window": int(window),
            "limit": int(limit),
            "count": len(table),
            "table": table,
            "cards": cards,  # por si quieres alertas detalladas
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}

def get_player_season_stats(player_id: int) -> Dict[str, Any]:
    """
    Stats acumuladas de temporada desde bootstrap elements:
    útil para: goles, asistencias, porterías en cero, atajadas, etc.
    """
    try:
        bootstrap = fetch_bootstrap_static()
        teams = _team_map(bootstrap)
        positions = _position_map(bootstrap)

        player = next((p for p in _players(bootstrap) if int(p["id"]) == int(player_id)), None)
        if not player:
            return {"status": "error", "message": f"player_id {player_id} no encontrado en bootstrap"}

        team_obj = teams.get(int(player.get("team")))
        pos_obj = positions.get(int(player.get("element_type", 0)), {})

        price_m = float(player.get("now_cost", 0)) / 10.0

        # Campos clave (todos vienen de bootstrap elements)
        payload = {
            "status": "ok",
            "player": {
                "player_id": int(player_id),
                "web_name": player.get("web_name"),
                "team": _normalize_team_name(team_obj or {}),
                "position": pos_obj.get("singular_name_short"),
                "now_cost_million": price_m,
                "status": player.get("status"),
                "chance_next_round": player.get("chance_of_playing_next_round"),
            },
            "season_stats": {
                "minutes": player.get("minutes"),
                "total_points": player.get("total_points"),
                "goals_scored": player.get("goals_scored"),
                "assists": player.get("assists"),
                "clean_sheets": player.get("clean_sheets"),
                "goals_conceded": player.get("goals_conceded"),
                "saves": player.get("saves"),
                "penalties_saved": player.get("penalties_saved"),
                "bonus": player.get("bonus"),
                "bps": player.get("bps"),
                "expected_goals": player.get("expected_goals"),
                "expected_assists": player.get("expected_assists"),
                "expected_goal_involvements": player.get("expected_goal_involvements"),
                "expected_goals_conceded": player.get("expected_goals_conceded"),
                "yellow_cards": player.get("yellow_cards"),
                "red_cards": player.get("red_cards"),
            }
        }

        return payload

    except Exception as e:
        return {"status": "error", "message": str(e)}

def get_top_scorers(position: str = "FWD", limit: int = 10) -> dict:
    try:
        bootstrap = fetch_bootstrap_static()
        teams = _team_map(bootstrap)
        positions = _position_map(bootstrap)

        pos_id = _position_id_from_code(position)
        if pos_id is None:
            return {"status": "error", "message": "position inválida"}

        rows = []
        for p in _players(bootstrap):
            if int(p.get("element_type", 0)) != pos_id:
                continue

            team_obj = teams.get(int(p.get("team")))
            price_m = float(p.get("now_cost", 0)) / 10.0

            rows.append({
                "player_id": int(p["id"]),
                "name": p.get("web_name"),
                "team": _normalize_team_name(team_obj or {}),
                "price_m": price_m,
                "goals_scored": int(p.get("goals_scored", 0) or 0),
                "minutes": int(p.get("minutes", 0) or 0),
                "total_points": int(p.get("total_points", 0) or 0),
            })

        rows.sort(key=lambda r: (r["goals_scored"], r["minutes"]), reverse=True)
        rows = rows[: int(limit)]

        return {
            "status": "ok",
            "position": position,
            "limit": int(limit),
            "results": rows
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

def get_top_players(metric: str, position: Optional[str] = None, limit: int = 10) -> Dict[str, Any]:
    """
    Ranking genérico por métrica acumulada de temporada (bootstrap elements).
    Ejemplos:
      - metric="goals_scored", position="FWD"
      - metric="assists", position=None
      - metric="clean_sheets", position="DEF"
      - metric="saves", position="GK"
    """
    try:
        allowed_metrics = {"goals_scored", "assists", "clean_sheets", "saves"}
        metric_norm = (metric or "").strip()

        if metric_norm not in allowed_metrics:
            return {
                "status": "error",
                "message": f"metric inválida '{metric}'. Allowed: {sorted(list(allowed_metrics))}"
            }

        bootstrap = fetch_bootstrap_static()
        teams = _team_map(bootstrap)
        positions = _position_map(bootstrap)

        pos_id = _position_id_from_code(position) if position else None
        lim = max(1, int(limit))

        rows = []
        for p in _players(bootstrap):
            if pos_id and int(p.get("element_type", 0)) != pos_id:
                continue

            team_obj = teams.get(int(p.get("team")))
            price_m = float(p.get("now_cost", 0) or 0) / 10.0
            metric_value = int(p.get(metric_norm, 0) or 0)

            rows.append({
                "player_id": int(p["id"]),
                "name": p.get("web_name"),
                "team": _normalize_team_name(team_obj or {}),
                "pos": positions.get(int(p.get("element_type", 0)), {}).get("singular_name_short"),
                "price_m": price_m,
                metric_norm: metric_value,
                "minutes": int(p.get("minutes", 0) or 0),
                "total_points": int(p.get("total_points", 0) or 0),
                "status": p.get("status"),
                "chance_next_round": p.get("chance_of_playing_next_round"),
            })

        # Orden: primero métrica desc, luego minutes desc (tie-break), luego total_points desc
        rows.sort(key=lambda r: (r.get(metric_norm, 0), r.get("minutes", 0), r.get("total_points", 0)), reverse=True)
        rows = rows[:lim]

        return {
            "status": "ok",
            "metric": metric_norm,
            "position_filter": position,
            "limit": lim,
            "results": rows
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


# (Opcional) wrapper para compatibilidad si ya estabas usando get_top_scorers
def get_top_scorers(position: str = "FWD", limit: int = 10) -> Dict[str, Any]:
    return get_top_players(metric="goals_scored", position=position, limit=limit)


##########
ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
MODEL_PATH = ARTIFACTS_DIR / "ridge_total_points_next_gw.joblib"
META_PATH = ARTIFACTS_DIR / "ridge_total_points_next_gw_meta.json"

_MODEL = None
_MODEL_META = None

def load_ridge_model():
    """Carga el modelo y meta 1 sola vez (cache en memoria)."""
    global _MODEL, _MODEL_META
    if _MODEL is not None and _MODEL_META is not None:
        return _MODEL, _MODEL_META

    if not MODEL_PATH.exists() or not META_PATH.exists():
        return None, None

    _MODEL = joblib.load(MODEL_PATH)
    _MODEL_META = json.loads(META_PATH.read_text(encoding="utf-8"))
    return _MODEL, _MODEL_META

#####
def _build_feature_row_from_card(card: dict, feature_cols: list, window: int) -> dict:
    """
    Convierte get_player_card(...) -> una fila con las columnas esperadas por el modelo.
    Importante: el notebook usó *rolling sums* con nombres tipo:
      total_points_roll_5, minutes_roll_5, expected_goals_roll_5, expected_assists_roll_5, ...
    Aquí reconstruimos esos nombres desde card["form"].
    """
    p = card["player"]
    f = card["form"]

    # mapeo: nuestras métricas -> nombres del dataset (roll_5)
    # card["form"] trae xG_last_n/xA_last_n/xGI_last_n, etc.
    base = {
        "now_cost_m": float(p.get("now_cost_million", 0.0) or 0.0),
        f"total_points_roll_{window}": float(f.get("points_last_n", 0) or 0),
        f"minutes_roll_{window}": float(f.get("minutes_last_n", 0) or 0),
        f"expected_goals_roll_{window}": float(f.get("xG_last_n", 0.0) or 0.0),
        f"expected_assists_roll_{window}": float(f.get("xA_last_n", 0.0) or 0.0),
        f"xGI_roll_{window}": float(f.get("xGI_last_n", 0.0) or 0.0),
        f"clean_sheets_roll_{window}": float(f.get("clean_sheets_last_n", 0) or 0),
        f"goals_conceded_roll_{window}": float(f.get("goals_conceded_last_n", 0) or 0),
        f"bps_roll_{window}": float(f.get("bps_last_n", 0) or 0),
        f"saves_roll_{window}": float(f.get("saves_last_n", 0) or 0),
    }

    # Si tu notebook incluyó means, los llenamos con aproximación simple:
    # mean ≈ sum / matches (si matches>0)
    matches = int(f.get("matches", 0) or 0)
    denom = max(matches, 1)
    base[f"total_points_mean_{window}"] = base[f"total_points_roll_{window}"] / denom
    base[f"minutes_mean_{window}"] = base[f"minutes_roll_{window}"] / denom
    base[f"bps_mean_{window}"] = base[f"bps_roll_{window}"] / denom

    # devolver solo columnas que el modelo espera (y el resto a 0)
    row = {c: 0.0 for c in feature_cols}
    for k, v in base.items():
        if k in row:
            row[k] = float(v)
    return row


def predict_next_gw_points(player_ids: list, gw: int) -> dict:
    model, meta = load_ridge_model()
    if model is None or meta is None:
        return {"status": "not_available", "message": "Modelo no encontrado en ./artifacts/"}

    window = int(meta.get("window", 5))
    feature_cols = meta["feature_cols"]

    rows = []
    ok_ids = []
    errors = {}

    for pid in player_ids:
        card = get_player_card(int(pid), int(gw), window=window, budget_million=None)
        if card.get("status") != "ok":
            errors[int(pid)] = card.get("message", "card error")
            continue
        ok_ids.append(int(pid))
        rows.append(_build_feature_row_from_card(card, feature_cols, window))

    if not rows:
        return {"status": "error", "message": "No se pudieron construir features para ningún player_id", "errors": errors}

    X = pd.DataFrame(rows, columns=feature_cols).fillna(0)
    preds = model.predict(X)

    return {
        "status": "ok",
        "gw": int(gw),
        "window": window,
        "predictions": [
            {"player_id": pid, "pred_total_points_next_gw": float(pred)}
            for pid, pred in zip(ok_ids, preds)
        ],
        "errors": errors,
    }

def get_player_gw_points(player_id: int, gw: Optional[int] = None) -> Dict[str, Any]:
    try:
        bootstrap = fetch_bootstrap_static()
        events = bootstrap.get("events", [])
        finished_gws = [e["id"] for e in events if e.get("finished") is True]
        last_finished = max(finished_gws) if finished_gws else None

        target_gw = int(gw) if gw else last_finished
        if not target_gw:
            return {"status": "error", "message": "No se pudo determinar GW anterior (último GW finished)."}

        summary = fetch_element_summary(int(player_id))
        hist = summary.get("history", [])

        row = next((r for r in hist if int(r.get("round", 0)) == target_gw), None)
        if not row:
            return {"status": "error", "message": f"No hay registro para GW{target_gw} en history."}

        return {
            "status": "ok",
            "player_id": int(player_id),
            "gw": int(target_gw),
            "total_points": int(row.get("total_points", 0) or 0),
            "minutes": int(row.get("minutes", 0) or 0),
            "goals_scored": int(row.get("goals_scored", 0) or 0),
            "assists": int(row.get("assists", 0) or 0),
            "clean_sheets": int(row.get("clean_sheets", 0) or 0),
            "goals_conceded": int(row.get("goals_conceded", 0) or 0),
            "saves": int(row.get("saves", 0) or 0),
            "bps": int(row.get("bps", 0) or 0),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}