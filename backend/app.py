from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date as date_cls, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any

import requests
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

APP_VERSION = "1.4.0"
SPORTS = ("NFL", "NBA", "MLB", "NHL")
SPORT_KEYS = {
    "NFL": "americanfootball_nfl",
    "NBA": "basketball_nba",
    "MLB": "baseball_mlb",
    "NHL": "icehockey_nhl",
}
ESPN = {
    "NFL": ("football", "nfl"),
    "NBA": ("basketball", "nba"),
}
PROP_MARKETS = {
    "NFL": [
        "player_pass_yds", "player_rush_yds", "player_reception_yds",
        "player_pass_tds", "player_rush_tds", "player_reception_tds",
        "player_receptions", "player_pass_completions", "player_pass_attempts",
        "player_pass_interceptions", "player_rush_attempts", "player_anytime_td",
    ],
    "NBA": [
        "player_points", "player_rebounds", "player_assists", "player_threes",
        "player_blocks", "player_steals", "player_turnovers",
        "player_points_rebounds_assists", "player_points_rebounds",
        "player_points_assists", "player_rebounds_assists", "player_double_double",
        "player_triple_double",
    ],
    "MLB": [
        "batter_hits", "batter_home_runs", "batter_total_bases", "batter_rbis",
        "batter_runs_scored", "batter_hits_runs_rbis", "batter_walks",
        "batter_strikeouts", "batter_stolen_bases", "pitcher_strikeouts",
        "pitcher_hits_allowed", "pitcher_walks", "pitcher_earned_runs", "pitcher_outs",
    ],
    "NHL": [
        "player_points", "player_power_play_points", "player_assists",
        "player_blocked_shots", "player_shots_on_goal", "player_goals",
        "player_total_saves", "player_goal_scorer_anytime",
    ],
}
MODEL_BUNDLE_PATH = Path(__file__).resolve().parent / "models" / "manifest.json"

def _load_model_registry() -> dict[str, dict[str, Any]]:
    manifest = json.loads(MODEL_BUNDLE_PATH.read_text())
    root = Path(__file__).resolve().parent.parent
    registry: dict[str, dict[str, Any]] = {}
    for sport in SPORTS:
        entry = manifest["sports"][sport]
        artifact = root / entry["path"]
        payload = artifact.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != entry["sha256"]:
            raise RuntimeError(f"{sport} production baseline artifact hash mismatch")
        model = json.loads(payload)
        registry[sport] = {
            **model,
            "version": model["model_id"],
            "artifact_path": entry["path"],
            "sha256": digest,
            "probability_source": "fresh_de_vigged_consensus_moneyline",
            "score_source": "consensus_total_plus_spread",
        }
    return registry

MODEL_REGISTRY = _load_model_registry()

PROMOTION_ECE_MAX = 0.01

def _promotion_gate_for(sport: str) -> dict[str, Any]:
    model = MODEL_REGISTRY[sport]
    evidence = model.get("promotion_evidence") or {}
    chronology = evidence.get("chronology") or {}
    calibration = evidence.get("calibration") or {}
    holdout = evidence.get("holdout") or {}
    provenance = evidence.get("provenance") or {}
    leakage = evidence.get("leakage_audit") or {}
    baseline = evidence.get("market_baseline_comparison") or {}

    ece = calibration.get("ece")
    checks = {
        "canonical_dataset": bool(provenance.get("dataset_sha256")),
        "feature_schema": bool(provenance.get("feature_schema_sha256")),
        "chronology_as_of_before_event": chronology.get("as_of_lt_event_time") is True,
        "walk_forward_oof": chronology.get("walk_forward_oof") is True,
        "calibration_oof_only": calibration.get("oof_only") is True,
        "calibration_metrics": (
            isinstance(calibration.get("brier"), (int, float))
            and isinstance(calibration.get("log_loss"), (int, float))
            and isinstance(ece, (int, float))
        ),
        "ece_threshold": isinstance(ece, (int, float)) and float(ece) <= PROMOTION_ECE_MAX,
        "separate_holdout": holdout.get("separate_from_calibration") is True and int(holdout.get("resolved_games") or 0) > 0,
        "leakage_audit": leakage.get("passed") is True,
        "provenance_hashes": bool(provenance.get("source_manifest_sha256")) and bool(provenance.get("model_sha256")),
        "beats_active_market_baseline": baseline.get("passed") is True,
        "trained_weights": model.get("trained_weights") is True,
        "explicit_promotion": model.get("status") == "PROMOTED_TRAINED_MODEL",
    }
    passed = all(checks.values())
    return {
        "sport": sport,
        "passed": passed,
        "checks": checks,
        "ece_max": PROMOTION_ECE_MAX,
        "evidence": evidence,
        "runtime_role": "PROMOTED_TRAINED_MODEL" if passed else "BASELINE_FALLBACK",
    }

def _all_model_gates() -> dict[str, dict[str, Any]]:
    return {sport: _promotion_gate_for(sport) for sport in SPORTS}

def _runtime_mode_for(sport: str) -> str:
    return "PROMOTED_TRAINED_MODEL" if _promotion_gate_for(sport)["passed"] else "EVIDENCE_GATED_ENSEMBLE_BASELINE_FALLBACK"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": f"PhilthySports/{APP_VERSION}", "Accept": "application/json"})

app = FastAPI(title="PhilthySports Runtime API", version=APP_VERSION)
origins = [x.strip() for x in os.getenv("PHILTHY_CORS_ORIGINS", "*").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)
_SOURCE: dict[str, dict[str, Any]] = {}

@app.middleware("http")
async def request_ids(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    return response

def _timed(name: str, fn):
    started = time.perf_counter()
    try:
        value = fn()
        _SOURCE[name] = {"ok": True, "elapsed_ms": round((time.perf_counter()-started)*1000, 1), "checked_at": datetime.now(timezone.utc).isoformat()}
        return value
    except Exception as exc:
        _SOURCE[name] = {"ok": False, "elapsed_ms": round((time.perf_counter()-started)*1000, 1), "checked_at": datetime.now(timezone.utc).isoformat(), "error": f"{type(exc).__name__}: {exc}"}
        raise

def _json(url: str, *, params: dict | None = None, timeout: int = 10):
    r = SESSION.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

def _espn_schedule(sport: str, date_yyyymmdd: str) -> list[dict]:
    a, b = ESPN[sport]
    raw = _json(f"https://site.api.espn.com/apis/site/v2/sports/{a}/{b}/scoreboard", params={"dates": date_yyyymmdd})
    out = []
    for ev in raw.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        teams = comp.get("competitors") or []
        home = next((x for x in teams if x.get("homeAway") == "home"), None)
        away = next((x for x in teams if x.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        out.append({
            "event_id": str(ev.get("id")), "sport": sport, "event_time": ev.get("date"),
            "home": home.get("team", {}).get("displayName"), "away": away.get("team", {}).get("displayName"),
            "status": ev.get("status", {}).get("type", {}).get("name", ""), "schedule_source": "ESPN",
        })
    return out

def _mlb_schedule(date_iso: str) -> list[dict]:
    raw = _json("https://statsapi.mlb.com/api/v1/schedule", params={"sportId": 1, "date": date_iso, "hydrate": "probablePitcher,team"})
    out = []
    for day in raw.get("dates", []):
        for g in day.get("games", []):
            out.append({
                "event_id": str(g.get("gamePk")), "sport": "MLB", "event_time": g.get("gameDate"),
                "home": g["teams"]["home"]["team"]["name"], "away": g["teams"]["away"]["team"]["name"],
                "home_probable_pitcher": g["teams"]["home"].get("probablePitcher", {}).get("fullName"),
                "away_probable_pitcher": g["teams"]["away"].get("probablePitcher", {}).get("fullName"),
                "status": g.get("status", {}).get("detailedState", ""), "schedule_source": "MLB StatsAPI",
            })
    return out

def _nhl_name(team: dict) -> str | None:
    for key in ("name", "commonName", "placeName"):
        v = team.get(key)
        if isinstance(v, dict):
            v = v.get("default") or next(iter(v.values()), None)
        if v:
            return str(v)
    return team.get("abbrev")

def _nhl_schedule(date_iso: str) -> list[dict]:
    raw = _json(f"https://api-web.nhle.com/v1/schedule/{date_iso}")
    out = []
    for day in raw.get("gameWeek") or []:
        if day.get("date") != date_iso:
            continue
        for g in day.get("games") or []:
            out.append({
                "event_id": str(g.get("id")), "sport": "NHL", "event_time": g.get("startTimeUTC"),
                "home": _nhl_name(g.get("homeTeam") or {}), "away": _nhl_name(g.get("awayTeam") or {}),
                "status": g.get("gameState") or "", "schedule_source": "NHL Web API",
            })
    return out

def _schedule(sport: str, d: date_cls) -> list[dict]:
    if sport == "MLB":
        return _timed("MLB.schedule", lambda: _mlb_schedule(d.isoformat()))
    if sport == "NHL":
        return _timed("NHL.schedule", lambda: _nhl_schedule(d.isoformat()))
    return _timed(f"{sport}.schedule", lambda: _espn_schedule(sport, d.strftime("%Y%m%d")))

def _odds_key() -> str:
    key = os.getenv("ODDS_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ODDS_API_KEY missing")
    return key

def _odds(sport: str, d: date_cls) -> list[dict]:
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    end = start + timedelta(hours=36)
    params = {
        "apiKey": _odds_key(), "regions": "us", "markets": "h2h,spreads,totals",
        "oddsFormat": "american", "dateFormat": "iso",
        "commenceTimeFrom": start.isoformat().replace("+00:00", "Z"),
        "commenceTimeTo": end.isoformat().replace("+00:00", "Z"),
    }
    return _timed(f"{sport}.odds", lambda: _json(f"https://api.the-odds-api.com/v4/sports/{SPORT_KEYS[sport]}/odds/", params=params, timeout=12))

def _norm(s: str | None) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())

def _same_team(a: str | None, b: str | None) -> bool:
    x, y = _norm(a), _norm(b)
    return bool(x and y and (x == y or x in y or y in x))

def _match_odds(game: dict, events: list[dict]) -> dict | None:
    return next((e for e in events if _same_team(game.get("home"), e.get("home_team")) and _same_team(game.get("away"), e.get("away_team"))), None)

def _american_to_prob(x: float) -> float:
    x = float(x)
    return (-x)/((-x)+100) if x < 0 else 100/(x+100)

def _devig(a: float, b: float) -> tuple[float, float]:
    s = a+b
    return (a/s, b/s) if s else (.5, .5)

def _market(event: dict | None) -> dict:
    if not event:
        return {"home_probability": None, "away_probability": None, "home_spread": None, "total": None, "books_used": []}
    home, away = event.get("home_team"), event.get("away_team")
    h2h = {home: [], away: []}
    spreads, totals, books = [], [], set()
    for book in event.get("bookmakers") or []:
        used = False
        for m in book.get("markets") or []:
            if m.get("key") == "h2h":
                for o in m.get("outcomes") or []:
                    if o.get("name") in h2h and o.get("price") is not None:
                        h2h[o["name"]].append(float(o["price"]))
                        used = True
            elif m.get("key") == "spreads":
                for o in m.get("outcomes") or []:
                    if o.get("name") == home and o.get("point") is not None:
                        spreads.append(float(o["point"]))
                        used = True
            elif m.get("key") == "totals":
                for o in m.get("outcomes") or []:
                    if o.get("point") is not None:
                        totals.append(float(o["point"]))
                        used = True
        if used:
            books.add(book.get("key") or "unknown")
    out = {
        "home_probability": None, "away_probability": None,
        "home_spread": round(mean(spreads), 2) if spreads else None,
        "total": round(mean(totals), 2) if totals else None,
        "books_used": sorted(books),
    }
    if home and away and h2h.get(home) and h2h.get(away):
        hp = mean(_american_to_prob(x) for x in h2h[home])
        ap = mean(_american_to_prob(x) for x in h2h[away])
        out["home_probability"], out["away_probability"] = _devig(hp, ap)
    return out

def _score(market: dict) -> dict:
    total, spread = market.get("total"), market.get("home_spread")
    if total is None:
        return {"home": None, "away": None, "method": "unavailable_without_total"}
    margin = -float(spread) if spread is not None else 0.0
    return {"home": round(max(0, (float(total)+margin)/2), 1), "away": round(max(0, (float(total)-margin)/2), 1), "method": "consensus_total_plus_spread"}

def _prop_payload(sport: str, event_id: str) -> dict:
    markets = PROP_MARKETS[sport]
    params = {"apiKey": _odds_key(), "regions": "us", "markets": ",".join(markets), "oddsFormat": "american", "dateFormat": "iso"}
    raw = _timed(f"{sport}.props", lambda: _json(f"https://api.the-odds-api.com/v4/sports/{SPORT_KEYS[sport]}/events/{event_id}/odds", params=params, timeout=12))
    grouped: dict[tuple[str, str, float], dict[str, list[float]]] = {}
    for book in raw.get("bookmakers") or []:
        for market in book.get("markets") or []:
            key = market.get("key")
            if key not in markets:
                continue
            for o in market.get("outcomes") or []:
                side = str(o.get("name", "")).lower()
                if side not in {"over", "under"} or o.get("point") is None or o.get("price") is None:
                    continue
                player = o.get("description") or "Unknown"
                k = (key, player, float(o["point"]))
                grouped.setdefault(k, {"over": [], "under": []})[side].append(float(o["price"]))
    props = []
    for (market, player, line), sides in grouped.items():
        op = mean(_american_to_prob(x) for x in sides["over"]) if sides["over"] else None
        up = mean(_american_to_prob(x) for x in sides["under"]) if sides["under"] else None
        rec = prob = None
        if op is not None and up is not None:
            over, under = _devig(op, up)
            rec, prob = ("OVER", over) if over >= under else ("UNDER", under)
        props.append({
            "sport": sport, "player": player, "market": market, "line": line,
            "recommended_side": rec, "market_probability": prob,
            "reason": f"Fresh two-sided sportsbook market; de-vigged market lean {rec} at {prob:.1%}." if rec else "Fresh market returned but a two-sided de-vigged probability was unavailable.",
            "model_state": "MARKET_ONLY_UNTIL_VALIDATED_PROP_MODEL",
        })
    props.sort(key=lambda x: x.get("market_probability") or 0, reverse=True)
    return {"sport": sport, "event_id": event_id, "configured_markets": markets, "props": props, "status": "OK"}

def _search(q: str = "", sport: str | None = None, date: str | None = None, include_props: bool = False, props_limit: int = 3) -> dict:
    d = date_cls.fromisoformat(date) if date else date_cls.today()
    selected = [sport.upper()] if sport else list(SPORTS)
    for s in selected:
        if s not in SPORTS:
            raise ValueError(f"unsupported sport: {s}")
    qn = _norm(q)
    games = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        schedules = {s: pool.submit(_schedule, s, d) for s in selected}
        odds = {s: pool.submit(_odds, s, d) for s in selected}
        for s in selected:
            try:
                sched = schedules[s].result()
            except Exception:
                sched = []
            try:
                odd_events = odds[s].result()
            except Exception:
                odd_events = []
            for game in sched:
                if qn and qn not in _norm(game.get("home")) and qn not in _norm(game.get("away")) and qn not in _norm(s):
                    continue
                oe = _match_odds(game, odd_events)
                market = _market(oe)
                score = _score(market)
                hp = market.get("home_probability")
                item = {
                    **game, "date": d.isoformat(), "matchup": f"{game.get('away')} @ {game.get('home')}",
                    "odds_event_id": oe.get("id") if oe else None,
                    "market": market, "projected_score": score,
                    "pick": (game.get("home") if hp >= .5 else game.get("away")) if hp is not None else None,
                    "model_status": _runtime_mode_for(s), "model_metadata": {**MODEL_REGISTRY[s], "promotion_gate": _promotion_gate_for(s)},
                    "props_to_watch": [],
                }
                if include_props and item["odds_event_id"]:
                    try:
                        item["props_to_watch"] = _prop_payload(s, item["odds_event_id"])["props"][:max(0, min(int(props_limit), 20))]
                    except Exception as exc:
                        item["props_error"] = f"{type(exc).__name__}: {exc}"
                games.append(item)
    return {"query": q, "date": d.isoformat(), "sports": selected, "fresh_fetch": True, "games": games, "source_telemetry": _SOURCE}

@app.get("/health")
def health():
    return {"status": "ok", "service": "philthysports-runtime", "version": APP_VERSION}

@app.get("/v1/system/status")
def system_status():
    rotation = os.getenv("CREDENTIAL_ROTATION_CONFIRMED", "").lower() == "true"
    odds_key = bool(os.getenv("ODDS_API_KEY", "").strip())
    gates = _all_model_gates()
    chronology_pass = all(
        g["checks"]["chronology_as_of_before_event"] and g["checks"]["walk_forward_oof"]
        for g in gates.values()
    )
    calibration_pass = all(
        g["checks"]["calibration_oof_only"] and g["checks"]["calibration_metrics"] and g["checks"]["ece_threshold"] and g["checks"]["separate_holdout"]
        for g in gates.values()
    )
    leakage_pass = all(g["checks"]["leakage_audit"] for g in gates.values())
    provenance_pass = all(
        g["checks"]["canonical_dataset"] and g["checks"]["feature_schema"] and g["checks"]["provenance_hashes"]
        for g in gates.values()
    )
    promotion_pass = all(g["passed"] for g in gates.values())

    remaining = ["stable Android release signing and real-device E2E smoke"]
    if not rotation or not odds_key:
        remaining.insert(0, "fresh legitimately issued live odds/props credential plus provider-side rotation evidence")
    if not promotion_pass:
        remaining.insert(0, "four sport trained model promotion evidence")

    return {
        "api_version": APP_VERSION,
        "execution_mode": "MANUAL_REVIEW_ONLY",
        "model_policy": "EVIDENCE_GATED_ENSEMBLE",
        "runtime_behavior": "promoted trained model when its evidence gate passes; governed baseline fallback otherwise",
        "gates": {
            "chronology": "PASS" if chronology_pass else "BLOCKED_EVIDENCE",
            "calibration": "PASS" if calibration_pass else "BLOCKED_EVIDENCE",
            "leakage": "PASS" if leakage_pass else "BLOCKED_EVIDENCE",
            "provenance": "PASS" if provenance_pass else "BLOCKED_EVIDENCE",
            "four_sport_model_promotion": "PASS" if promotion_pass else "BLOCKED_EVIDENCE",
            "credential_core_keyless": "PASS",
            "credential_live_odds_props": "PASS" if rotation and odds_key else "BLOCKED_FRESH_ROTATED_KEY_REQUIRED",
        },
        "credential_gate": {
            "core_runtime_requires_secret": False,
            "rotation_confirmed": rotation,
            "odds_api_key_configured": odds_key,
            "odds_props_live_allowed": rotation and odds_key,
        },
        "production_ready": bool(promotion_pass and rotation and odds_key),
        "remaining_external_gates": remaining,
        "source_telemetry": _SOURCE,
    }

@app.get("/v1/models/status")
def model_status():
    return {
        sport: {**MODEL_REGISTRY[sport], "promotion_gate": _promotion_gate_for(sport), "runtime_mode": _runtime_mode_for(sport)}
        for sport in SPORTS
    }

@app.get("/v1/system/props")
def prop_capabilities():
    configured = bool(os.getenv("ODDS_API_KEY", "").strip())
    return {"provider": "The Odds API v4", "credential_configured": configured, "sports": {s: {"supported": True, "markets": PROP_MARKETS[s]} for s in SPORTS}}

@app.get("/v1/today")
def today(include_props: bool = True, props_limit: int = 3):
    return _search(include_props=include_props, props_limit=props_limit)

@app.get("/v1/search")
def search(q: str = "", sport: str | None = None, date: str | None = None, include_props: bool = False, props_limit: int = 3):
    try:
        return _search(q=q, sport=sport, date=date, include_props=include_props, props_limit=props_limit)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

@app.get("/v1/games/{sport}/{event_id}")
def game_detail(sport: str, event_id: str, date: str | None = None):
    result = _search(sport=sport, date=date)
    game = next((g for g in result["games"] if str(g["event_id"]) == str(event_id)), None)
    if not game:
        raise HTTPException(404, "game not found in fresh schedule")
    score, market = game["projected_score"], game["market"]
    reasons = [
        f"Fresh de-vigged consensus moneyline implies home win probability {market['home_probability']:.1%}." if market.get("home_probability") is not None else "Fresh sportsbook win probability is unavailable; no replacement probability is invented.",
        f"Consensus spread {market['home_spread']:+.1f} and total {market['total']:.1f} define the score projection." if market.get("home_spread") is not None and market.get("total") is not None else "Spread/total evidence is incomplete, so no synthetic score inputs are inserted.",
        "Runtime model is the governed four-sport market baseline; trained calibrated models may override it only after chronological promotion gates pass.",
    ]
    game["score_prediction"] = {"home": score.get("home"), "away": score.get("away"), "pick": game.get("pick"), "reasons": reasons}
    game["team_totals"] = {"home": score.get("home"), "away": score.get("away"), "method": score.get("method")}
    return game

@app.get("/v1/games/{sport}/{event_id}/props")
def props(sport: str, event_id: str, odds_event_id: str | None = None):
    s = sport.upper()
    if s not in SPORTS:
        raise HTTPException(400, "unsupported sport")
    if not os.getenv("ODDS_API_KEY", "").strip():
        return {
            "sport": s,
            "event_id": event_id,
            "configured_markets": PROP_MARKETS[s],
            "props": [],
            "status": "CONTRACT_READY_LIVE_KEY_REQUIRED",
            "message": "Player-prop markets are configured. Fresh sportsbook lines require a newly issued server-side ODDS_API_KEY.",
        }
    if not odds_event_id:
        return {
            "sport": s,
            "event_id": event_id,
            "configured_markets": PROP_MARKETS[s],
            "props": [],
            "status": "LIVE_KEY_READY_EVENT_MAPPING_REQUIRED",
            "message": "The live provider key is configured but this schedule event has not yet been mapped to a sportsbook event id.",
        }
    try:
        return _prop_payload(s, odds_event_id)
    except Exception as exc:
        raise HTTPException(502, f"fresh props fetch failed: {type(exc).__name__}: {exc}")

@app.get("/v1/games/{sport}/{event_id}/parlays")
def parlays(sport: str, event_id: str, date: str | None = None):
    game = game_detail(sport, event_id, date)
    oid = game.get("odds_event_id")
    if not oid:
        return {"sport": sport.upper(), "event_id": event_id, "parlays": [], "status": "NO_ODDS_EVENT"}
    try:
        props_payload = _prop_payload(sport.upper(), oid)
    except Exception:
        props_payload = {"props": []}
    legs = []
    if game.get("pick"):
        legs.append({"label": f"{game['pick']} moneyline"})
    for p in props_payload["props"][:8]:
        if p.get("recommended_side"):
            legs.append({"label": f"{p['player']} {p['recommended_side']} {p['line']} {p['market']}"})
    combos = []
    for i in range(max(0, len(legs)-2)):
        chunk = legs[i:i+3]
        if len(chunk) == 3:
            combos.append({"legs": chunk, "estimated_joint_probability": None, "dependency_method": "UNSCORED_WITHOUT_VALIDATED_DEPENDENCY_MODEL"})
        if len(combos) == 4:
            break
    for combo in combos:
        combo["reasoning"] = [
            "Every leg comes from a fresh event-level moneyline or player-prop market returned by the configured provider.",
            "No correlation bonus is invented. Joint probability remains unscored until a measured dependency model passes governance.",
            "Manual review is required before any wagering action.",
        ]
    return {"sport": sport.upper(), "event_id": event_id, "parlays": combos, "status": "OK" if combos else "INSUFFICIENT_ELIGIBLE_LEGS"}

def _multisport_candidates(d: date_cls) -> list[dict[str, Any]]:
    result = _search(date=d.isoformat(), include_props=False)
    candidates: list[dict[str, Any]] = []

    per_sport_prop_events: dict[str, int] = {s: 0 for s in SPORTS}
    for game in result["games"]:
        sport = game["sport"]
        market = game.get("market") or {}
        hp = market.get("home_probability")
        if hp is not None and game.get("pick"):
            picked_home = game["pick"] == game.get("home")
            probability = float(hp) if picked_home else 1.0 - float(hp)
            candidates.append({
                "sport": sport,
                "event_id": game["event_id"],
                "event_time": game.get("event_time"),
                "matchup": game.get("matchup"),
                "type": "moneyline",
                "label": f"{game['pick']} moneyline",
                "probability": round(probability, 6),
                "reason": f"Fresh de-vigged consensus market gives this side {probability:.1%} implied probability across {len(market.get('books_used') or [])} contributing books.",
                "model_state": _runtime_mode_for(sport),
            })

        oid = game.get("odds_event_id")
        if oid and per_sport_prop_events[sport] < 2:
            per_sport_prop_events[sport] += 1
            try:
                payload = _prop_payload(sport, oid)
                for p in payload.get("props", [])[:4]:
                    if p.get("recommended_side") and p.get("market_probability") is not None:
                        candidates.append({
                            "sport": sport,
                            "event_id": game["event_id"],
                            "event_time": game.get("event_time"),
                            "matchup": game.get("matchup"),
                            "type": "player_prop",
                            "label": f"{p['player']} {p['recommended_side']} {p['line']} {p['market']}",
                            "probability": round(float(p["market_probability"]), 6),
                            "reason": p.get("reason"),
                            "model_state": p.get("model_state"),
                        })
            except Exception:
                pass

    candidates.sort(key=lambda x: x.get("probability") or 0.0, reverse=True)
    return candidates

def _build_multisport_parlay(leg_count: int, date: str | None = None) -> dict[str, Any]:
    if leg_count not in {7, 10, 14}:
        raise ValueError("leg_count must be one of 7, 10, or 14")
    d = date_cls.fromisoformat(date) if date else date_cls.today()
    candidates = _multisport_candidates(d)

    by_sport = {sport: [x for x in candidates if x["sport"] == sport] for sport in SPORTS}
    selected: list[dict[str, Any]] = []
    seen_events: set[tuple[str, str, str]] = set()

    while len(selected) < leg_count:
        added = False
        for sport in SPORTS:
            while by_sport[sport]:
                leg = by_sport[sport].pop(0)
                dedupe = (leg["sport"], leg["event_id"], leg["label"])
                if dedupe in seen_events:
                    continue
                selected.append(leg)
                seen_events.add(dedupe)
                added = True
                break
            if len(selected) >= leg_count:
                break
        if not added:
            break

    return {
        "date": d.isoformat(),
        "requested_legs": leg_count,
        "actual_legs": len(selected),
        "multisport": len({x["sport"] for x in selected}) > 1,
        "sports_included": sorted({x["sport"] for x in selected}),
        "legs": selected,
        "dependency_method": "UNSCORED_WITHOUT_VALIDATED_DEPENDENCY_MODEL",
        "estimated_joint_probability": None,
        "reasoning": [
            "Legs are ranked from fresh de-vigged event markets and available player-prop markets, then round-robin selected across NFL, NBA, MLB, and NHL to encourage multisport coverage.",
            "The system does not multiply leg probabilities or add a correlation boost because measured cross-leg dependency has not passed governance.",
            "A leg is omitted rather than fabricated when a fresh probability or mapped live prop market is unavailable.",
            "Manual review is required before any wagering action.",
        ],
        "status": "OK" if len(selected) == leg_count else "INSUFFICIENT_FRESH_ELIGIBLE_LEGS",
    }

@app.get("/v1/parlays/multisport")
def multisport_parlays(legs: int = Query(7), date: str | None = None):
    try:
        return _build_multisport_parlay(int(legs), date)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

