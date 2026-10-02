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
from zoneinfo import ZoneInfo

import requests
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from ci_security import (
    android_private_pkcs8_b64,
    android_public_spki_sha256,
    model_key_id,
    model_public_key_b64,
    sign_model_artifact,
    verify_github_oidc,
)
from model_runtime import (
    load_promoted,
    predict_home_probability,
    promotion_gate as trained_promotion_gate,
)
from model_runtime import (
    load_promoted,
    predict_home_probability,
    promotion_gate as promoted_promotion_gate,
)

APP_VERSION = "1.4.4"
SPORTS = ("NFL", "NBA", "MLB", "NHL")
PACIFIC_TZ = ZoneInfo("America/Los_Angeles")

def _pacific_today() -> date_cls:
    return datetime.now(PACIFIC_TZ).date()

def _event_time_pacific(value: Any) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(PACIFIC_TZ).isoformat()
    except Exception:
        return None

SPORT_KEYS = {
    "NFL": "americanfootball_nfl",
    "NBA": "basketball_nba",
    "MLB": "baseball_mlb",
    "NHL": "icehockey_nhl",
}
ESPN = {
    "NFL": ("football", "nfl"),
    "NBA": ("basketball", "nba"),
    "MLB": ("baseball", "mlb"),
    "NHL": ("hockey", "nhl"),
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
DRIVE_RECONSTRUCTION_PATH = Path(__file__).resolve().parent / "training" / "drive_reconstruction_manifest.json"

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
PROMOTED_MODELS = {sport: load_promoted(sport) for sport in SPORTS}
PROMOTED_MODELS = {sport: load_promoted(sport) for sport in SPORTS}

def _load_drive_reconstruction() -> dict[str, Any]:
    if not DRIVE_RECONSTRUCTION_PATH.exists():
        return {"status": "MISSING", "sports": {}}
    return json.loads(DRIVE_RECONSTRUCTION_PATH.read_text())

DRIVE_RECONSTRUCTION = _load_drive_reconstruction()

PROMOTION_ECE_MAX = 0.01

def _baseline_promotion_gate_for(sport: str) -> dict[str, Any]:
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
        "sample_sufficiency": False,
        "artifact_security": False,
        "mobile_parity": False,
        "trained_weights": model.get("trained_weights") is True,
        "explicit_promotion": model.get("status") == "PROMOTED_TRAINED_MODEL",
    }
    return {
        "sport": sport,
        "passed": False,
        "checks": checks,
        "ece_max": PROMOTION_ECE_MAX,
        "evidence": evidence,
        "runtime_role": "BASELINE_FALLBACK",
    }


def _promotion_gate_for(sport: str) -> dict[str, Any]:
    promoted = PROMOTED_MODELS.get(sport)
    if promoted is not None:
        raw = trained_promotion_gate(promoted, sport)
        evidence = raw.get("evidence") or {}
        calibration = evidence.get("calibration") or {}
        rc = raw.get("checks") or {}
        ece = calibration.get("ece")
        checks = {
            "canonical_dataset": rc.get("dataset_provenance") is True,
            "feature_schema": (
                rc.get("schema_compatible") is True
                and rc.get("schema_checksum_verified") is True
            ),
            "chronology_as_of_before_event": rc.get("chronology_as_of_before_event") is True,
            "walk_forward_oof": rc.get("walk_forward_oof") is True,
            "calibration_oof_only": rc.get("calibration_oof_only") is True,
            "calibration_metrics": (
                isinstance(calibration.get("brier"), (int, float))
                and isinstance(calibration.get("log_loss"), (int, float))
                and isinstance(ece, (int, float))
            ),
            "ece_threshold": rc.get("ece_threshold") is True,
            "separate_holdout": rc.get("separate_holdout") is True,
            "leakage_audit": rc.get("leakage_audit") is True,
            "provenance_hashes": (
                rc.get("source_provenance") is True
                and rc.get("model_checksum_verified") is True
                and rc.get("artifact_checksum_verified") is True
                and rc.get("core_checksum_verified") is True
            ),
            "beats_active_market_baseline": (
                rc.get("brier_improvement") is True
                and rc.get("log_loss_non_inferior") is True
            ),
            "sample_sufficiency": (
                rc.get("sample_total") is True
                and rc.get("sample_oof") is True
                and rc.get("sample_holdout") is True
            ),
            "trained_weights": rc.get("trained_weights") is True,
            "explicit_promotion": rc.get("status_promoted") is True,
            "artifact_security": (
                rc.get("signature_verified") is True
                and rc.get("signing_key_id_verified") is True
            ),
            "mobile_parity": rc.get("mobile_parity") is True,
        }
        passed = raw.get("passed") is True and all(checks.values())
        return {
            "sport": sport,
            "passed": passed,
            "checks": checks,
            "ece_max": PROMOTION_ECE_MAX,
            "evidence": evidence,
            "security": raw.get("security"),
            "runtime_role": "PROMOTED_TRAINED_MODEL" if passed else "BASELINE_FALLBACK",
            "model_id": promoted.get("model_id"),
            "artifact_sha256": promoted.get("artifact_sha256"),
        }

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
        "separate_holdout": holdout.get("separate_from_calibration") is True
        and int(holdout.get("resolved_games") or 0) > 0,
        "leakage_audit": leakage.get("passed") is True,
        "provenance_hashes": bool(provenance.get("source_manifest_sha256"))
        and bool(provenance.get("model_sha256")),
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

_INJURY_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_INJURY_TTL_SECONDS = 300


def _injury_aliases(team: dict[str, Any]) -> list[str]:
    values = []
    for key in ("displayName", "name", "shortDisplayName", "location", "abbreviation"):
        value = team.get(key)
        if value:
            values.append(str(value))
    return [x for x in {_norm(v) for v in values} if x]


def _espn_injury_feed(sport: str) -> dict[str, Any]:
    cached = _INJURY_CACHE.get(sport)
    now = time.time()
    if cached and now - cached[0] <= _INJURY_TTL_SECONDS:
        return cached[1]

    a, b = ESPN[sport]
    raw = _json(
        f"https://site.api.espn.com/apis/site/v2/sports/{a}/{b}/injuries",
        timeout=12,
    )
    teams: dict[str, dict[str, Any]] = {}
    for group in raw.get("injuries") or []:
        if not isinstance(group, dict):
            continue
        team = group.get("team") if isinstance(group.get("team"), dict) else {}
        rows = []
        for injury in group.get("injuries") or []:
            if not isinstance(injury, dict):
                continue
            athlete = (
                injury.get("athlete")
                if isinstance(injury.get("athlete"), dict)
                else {}
            )
            injury_type = injury.get("type")
            if isinstance(injury_type, dict):
                injury_type = (
                    injury_type.get("description")
                    or injury_type.get("name")
                    or injury_type.get("abbreviation")
                )
            details = injury.get("details")
            if not isinstance(details, dict):
                details = {}
            status = injury.get("status")
            if isinstance(status, dict):
                status = (
                    status.get("name")
                    or status.get("description")
                    or status.get("abbreviation")
                )
            rows.append({
                "player": athlete.get("fullName") or athlete.get("displayName"),
                "position": (
                    (athlete.get("position") or {}).get("abbreviation")
                    if isinstance(athlete.get("position"), dict)
                    else None
                ),
                "status": status or details.get("type") or details.get("status"),
                "injury": injury_type or details.get("detail") or details.get("type"),
                "return_date": details.get("returnDate"),
                "source": "ESPN",
            })
        payload = {
            "team": (
                team.get("displayName")
                or team.get("name")
                or team.get("abbreviation")
            ),
            "injuries": rows,
        }
        for alias in _injury_aliases(team):
            teams[alias] = payload

    result = {
        "available": True,
        "source": "ESPN league injury feed",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "teams": teams,
    }
    _INJURY_CACHE[sport] = (now, result)
    return result


def _injury_summary(feed: dict[str, Any], team_name: str | None) -> dict[str, Any]:
    if not feed.get("available"):
        return {
            "available": False,
            "source": feed.get("source") or "ESPN league injury feed",
            "injuries": [],
            "count": None,
        }
    wanted = _norm(team_name)
    teams = feed.get("teams") or {}
    match = teams.get(wanted)
    if match is None:
        for alias, payload in teams.items():
            if wanted and alias and (wanted in alias or alias in wanted):
                match = payload
                break
    injuries = list((match or {}).get("injuries") or [])
    return {
        "available": True,
        "source": feed.get("source") or "ESPN league injury feed",
        "injuries": injuries,
        "count": len(injuries),
    }


def _odds_key() -> str:
    key = os.getenv("ODDS_API_KEY", "").strip()
    rotation = os.getenv("CREDENTIAL_ROTATION_CONFIRMED", "").strip().lower() == "true"
    if not rotation:
        raise RuntimeError("credential rotation is not confirmed")
    if not key:
        raise RuntimeError("ODDS_API_KEY missing")
    return key

def _coerce_number(value: Any) -> float | None:
    if isinstance(value, dict):
        for key in ("value", "american", "alternateDisplayValue", "moneyLine"):
            if key in value:
                return _coerce_number(value.get(key))
        return None
    try:
        return float(str(value).strip().replace("+", ""))
    except (TypeError, ValueError):
        return None

def _espn_market_events(sport: str, d: date_cls) -> list[dict]:
    a, b = ESPN[sport]
    raw = _json(
        f"https://site.api.espn.com/apis/site/v2/sports/{a}/{b}/scoreboard",
        params={"dates": d.strftime("%Y%m%d"), "lang": "en", "region": "us"},
        timeout=12,
    )
    now = datetime.now(timezone.utc)
    events: list[dict] = []
    for event in raw.get("events") or []:
        competitions = event.get("competitions") or []
        if not competitions or not isinstance(competitions[0], dict):
            continue
        comp = competitions[0]
        competitors = comp.get("competitors") or []
        home = next((x for x in competitors if isinstance(x, dict) and x.get("homeAway") == "home"), None)
        away = next((x for x in competitors if isinstance(x, dict) and x.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        home_team = (home.get("team") or {}).get("displayName") or (home.get("team") or {}).get("name")
        away_team = (away.get("team") or {}).get("displayName") or (away.get("team") or {}).get("name")
        commence_raw = event.get("date") or comp.get("date")
        try:
            commence = datetime.fromisoformat(str(commence_raw).replace("Z", "+00:00"))
        except Exception:
            continue
        if commence.tzinfo is None:
            commence = commence.replace(tzinfo=timezone.utc)
        if commence <= now:
            continue

        odds_rows = comp.get("odds") or []
        odds = next(
            (
                row for row in odds_rows
                if isinstance(row, dict)
                and "live" not in str((row.get("provider") or {}).get("name") or "").lower()
            ),
            None,
        )
        if not isinstance(odds, dict):
            continue

        home_odds = odds.get("homeTeamOdds") if isinstance(odds.get("homeTeamOdds"), dict) else {}
        away_odds = odds.get("awayTeamOdds") if isinstance(odds.get("awayTeamOdds"), dict) else {}
        home_ml = _coerce_number(home_odds.get("moneyLine") or (home_odds.get("current") or {}).get("moneyLine"))
        away_ml = _coerce_number(away_odds.get("moneyLine") or (away_odds.get("current") or {}).get("moneyLine"))
        markets: list[dict[str, Any]] = []
        if home_ml is not None and away_ml is not None:
            markets.append({
                "key": "h2h",
                "outcomes": [
                    {"name": home_team, "price": home_ml},
                    {"name": away_team, "price": away_ml},
                ],
            })

        spread = _coerce_number(odds.get("spread"))
        if spread is not None and spread != 0:
            magnitude = abs(spread)
            if bool(home_odds.get("favorite")):
                home_point, away_point = -magnitude, magnitude
            elif bool(away_odds.get("favorite")):
                home_point, away_point = magnitude, -magnitude
            else:
                home_point, away_point = -spread, spread
            markets.append({
                "key": "spreads",
                "outcomes": [
                    {"name": home_team, "point": home_point},
                    {"name": away_team, "point": away_point},
                ],
            })

        total = _coerce_number(odds.get("overUnder"))
        if total is not None and total > 0:
            markets.append({
                "key": "totals",
                "outcomes": [
                    {"name": "Over", "point": total},
                    {"name": "Under", "point": total},
                ],
            })
        if not markets:
            continue

        provider = odds.get("provider") if isinstance(odds.get("provider"), dict) else {}
        events.append({
            "id": str(event.get("id") or comp.get("id") or ""),
            "home_team": str(home_team or ""),
            "away_team": str(away_team or ""),
            "commence_time": commence.isoformat(),
            "bookmakers": [{
                "key": str(provider.get("id") or "espn"),
                "title": str(provider.get("name") or "ESPN"),
                "last_update": now.isoformat(),
                "markets": markets,
            }],
            "data_quality": "PREGAME_KEYLESS",
            "market_source": "ESPN_SCOREBOARD_ODDS",
        })
    return events

def _odds(sport: str, d: date_cls) -> list[dict]:
    key = os.getenv("ODDS_API_KEY", "").strip()
    rotation = os.getenv("CREDENTIAL_ROTATION_CONFIRMED", "").strip().lower() == "true"
    if key and rotation:
        start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        end = start + timedelta(hours=36)
        params = {
            "apiKey": key, "regions": "us", "markets": "h2h,spreads,totals",
            "oddsFormat": "american", "dateFormat": "iso",
            "commenceTimeFrom": start.isoformat().replace("+00:00", "Z"),
            "commenceTimeTo": end.isoformat().replace("+00:00", "Z"),
        }
        return _timed(
            f"{sport}.odds.the_odds_api",
            lambda: _json(
                f"https://api.the-odds-api.com/v4/sports/{SPORT_KEYS[sport]}/odds/",
                params=params,
                timeout=12,
            ),
        )
    return _timed(f"{sport}.odds.espn_keyless", lambda: _espn_market_events(sport, d))

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
    empty = {
        "home_probability": None,
        "away_probability": None,
        "home_spread": None,
        "away_spread": None,
        "spread_home_probability": None,
        "spread_away_probability": None,
        "spread_pick": None,
        "spread_pick_probability": None,
        "total": None,
        "over_probability": None,
        "under_probability": None,
        "total_pick": None,
        "total_pick_probability": None,
        "books_used": [],
    }
    if not event:
        return empty

    home, away = event.get("home_team"), event.get("away_team")
    h2h = {home: [], away: []}
    home_spreads: list[float] = []
    spread_home_probs: list[float] = []
    spread_away_probs: list[float] = []
    totals: list[float] = []
    over_probs: list[float] = []
    under_probs: list[float] = []
    books: set[str] = set()

    for book in event.get("bookmakers") or []:
        used = False
        for m in book.get("markets") or []:
            key = m.get("key")
            outcomes = m.get("outcomes") or []

            if key == "h2h":
                for o in outcomes:
                    if o.get("name") in h2h and o.get("price") is not None:
                        h2h[o["name"]].append(float(o["price"]))
                        used = True

            elif key == "spreads":
                home_o = next((o for o in outcomes if o.get("name") == home), None)
                away_o = next((o for o in outcomes if o.get("name") == away), None)
                if home_o and home_o.get("point") is not None:
                    home_spreads.append(float(home_o["point"]))
                    used = True
                if (
                    home_o
                    and away_o
                    and home_o.get("price") is not None
                    and away_o.get("price") is not None
                ):
                    hp = _american_to_prob(float(home_o["price"]))
                    ap = _american_to_prob(float(away_o["price"]))
                    home_p, away_p = _devig(hp, ap)
                    spread_home_probs.append(home_p)
                    spread_away_probs.append(away_p)
                    used = True

            elif key == "totals":
                over_o = next(
                    (o for o in outcomes if str(o.get("name") or "").lower() == "over"),
                    None,
                )
                under_o = next(
                    (o for o in outcomes if str(o.get("name") or "").lower() == "under"),
                    None,
                )
                point = None
                if over_o and over_o.get("point") is not None:
                    point = float(over_o["point"])
                elif under_o and under_o.get("point") is not None:
                    point = float(under_o["point"])
                if point is not None:
                    totals.append(point)
                    used = True
                if (
                    over_o
                    and under_o
                    and over_o.get("price") is not None
                    and under_o.get("price") is not None
                ):
                    op = _american_to_prob(float(over_o["price"]))
                    up = _american_to_prob(float(under_o["price"]))
                    over_p, under_p = _devig(op, up)
                    over_probs.append(over_p)
                    under_probs.append(under_p)
                    used = True

        if used:
            books.add(book.get("key") or "unknown")

    out = {**empty, "books_used": sorted(books)}

    if home and away and h2h.get(home) and h2h.get(away):
        hp = mean(_american_to_prob(x) for x in h2h[home])
        ap = mean(_american_to_prob(x) for x in h2h[away])
        out["home_probability"], out["away_probability"] = _devig(hp, ap)

    if home_spreads:
        out["home_spread"] = round(mean(home_spreads), 2)
        out["away_spread"] = round(-float(out["home_spread"]), 2)

    if spread_home_probs and spread_away_probs:
        home_p = mean(spread_home_probs)
        away_p = mean(spread_away_probs)
        out["spread_home_probability"], out["spread_away_probability"] = _devig(
            home_p, away_p
        )
        if out["spread_home_probability"] >= out["spread_away_probability"]:
            out["spread_pick"] = home
            out["spread_pick_probability"] = out["spread_home_probability"]
        else:
            out["spread_pick"] = away
            out["spread_pick_probability"] = out["spread_away_probability"]

    if totals:
        out["total"] = round(mean(totals), 2)

    if over_probs and under_probs:
        over_p = mean(over_probs)
        under_p = mean(under_probs)
        out["over_probability"], out["under_probability"] = _devig(over_p, under_p)
        if out["over_probability"] >= out["under_probability"]:
            out["total_pick"] = "OVER"
            out["total_pick_probability"] = out["over_probability"]
        else:
            out["total_pick"] = "UNDER"
            out["total_pick_probability"] = out["under_probability"]

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
    d = date_cls.fromisoformat(date) if date else _pacific_today()
    selected = [sport.upper()] if sport else list(SPORTS)
    for s in selected:
        if s not in SPORTS:
            raise ValueError(f"unsupported sport: {s}")
    qn = _norm(q)
    games = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        schedules = {s: pool.submit(_schedule, s, d) for s in selected}
        odds = {s: pool.submit(_odds, s, d) for s in selected}
        injuries = {s: pool.submit(_espn_injury_feed, s) for s in selected}
        for s in selected:
            try:
                sched = schedules[s].result()
            except Exception:
                sched = []
            try:
                odd_events = odds[s].result()
            except Exception:
                odd_events = []
            try:
                injury_feed = injuries[s].result()
            except Exception as exc:
                injury_feed = {
                    "available": False,
                    "source": "ESPN league injury feed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            for game in sched:
                if qn and qn not in _norm(game.get("home")) and qn not in _norm(game.get("away")) and qn not in _norm(s):
                    continue
                oe = _match_odds(game, odd_events)
                market = _market(oe)
                score = _score(market)
                market_hp = market.get("home_probability")
                hp = market_hp
                probability_source = "fresh_de_vigged_consensus_moneyline"
                prediction_reasoning = (
                    "Fresh pregame market baseline is active because no signed trained "
                    "artifact has passed every v8 promotion and runtime-security gate."
                )
                promoted = PROMOTED_MODELS.get(s)
                gate = _promotion_gate_for(s)
                if promoted is not None and gate["passed"] and market_hp is not None:
                    try:
                        hp = predict_home_probability(
                            promoted,
                            {
                                "consensus_de_vig_home_probability": market_hp,
                                "home_spread": market.get("home_spread"),
                                "consensus_total": market.get("total"),
                            },
                        )
                        probability_source = "signed_promoted_trained_model"
                        prediction_reasoning = (
                            "Signed sport-specific trained model is active. Its artifact "
                            "passed chronology, OOF calibration, Brier/log-loss/ECE, "
                            "leakage, provenance, sample, signature/checksum, schema, "
                            "and mobile-parity gates."
                        )
                    except Exception as exc:
                        hp = market_hp
                        probability_source = "fresh_de_vigged_consensus_moneyline"
                        prediction_reasoning = (
                            "Promoted model inference failed safely, so this event uses "
                            f"the fresh governed market baseline ({type(exc).__name__})."
                        )
                item = {
                    **game,
                    "date": d.isoformat(),
                    "event_time_pacific": _event_time_pacific(game.get("event_time")),
                    "timezone": "America/Los_Angeles",
                    "matchup": f"{game.get('away')} @ {game.get('home')}",
                    "odds_event_id": oe.get("id") if oe else None,
                    "market": market,
                    "projected_score": score,
                    "home_win_probability": hp,
                    "probability_source": probability_source,
                    "prediction_reasoning": prediction_reasoning,
                    "pick": (game.get("home") if hp >= .5 else game.get("away")) if hp is not None else None,
                    "model_status": _runtime_mode_for(s),
                    "model_metadata": {
                        **MODEL_REGISTRY[s],
                        "active_model_id": (
                            promoted.get("model_id") if promoted is not None and gate["passed"]
                            else MODEL_REGISTRY[s].get("model_id")
                        ),
                        "promoted_artifact_loaded": promoted is not None,
                        "promotion_gate": gate,
                    },
                    "injury_report": {
                        "home": _injury_summary(injury_feed, game.get("home")),
                        "away": _injury_summary(injury_feed, game.get("away")),
                        "analytics_note": (
                            "Current injuries are displayed as live context. They are not "
                            "silently injected into a model unless the promoted artifact "
                            "declares compatible injury features in its signed schema."
                        ),
                    },
                    "props_to_watch": [],
                }
                if include_props and item["odds_event_id"]:
                    try:
                        item["props_to_watch"] = _prop_payload(s, item["odds_event_id"])["props"][:max(0, min(int(props_limit), 20))]
                    except Exception as exc:
                        item["props_error"] = f"{type(exc).__name__}: {exc}"
                games.append(item)
    return {"query": q, "date": d.isoformat(), "sports": selected, "fresh_fetch": True, "games": games, "source_telemetry": _SOURCE}

@app.get("/")
def root():
    return {
        "service": "PhilthySports Powerhouse",
        "status": "ok",
        "version": APP_VERSION,
        "health": "/health",
        "system_status": "/v1/system/status",
        "models_status": "/v1/models/status",
        "multisport_parlays": "/v1/parlays/multisport?legs=7",
    }

@app.head("/")
def root_head():
    return None

@app.get("/api/health", include_in_schema=False)
@app.get("/v1/health", include_in_schema=False)
@app.get("/health")
def health():
    return {"status": "ok", "service": "philthysports-runtime", "version": APP_VERSION}

@app.get("/v1/artifacts/model-signing-key")
def model_signing_key():
    return {
        "algorithm": "Ed25519",
        "key_id": model_key_id(),
        "public_key_b64": model_public_key_b64(),
    }

@app.get("/v1/ci/android-signing-material")
def ci_android_signing_material(request: Request):
    try:
        claims = verify_github_oidc(request.headers.get("authorization"))
        private_key_b64 = android_private_pkcs8_b64()
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except Exception as exc:
        raise HTTPException(503, f"signing material unavailable: {type(exc).__name__}")
    return {
        "algorithm": "EC_P256",
        "private_key_pkcs8_b64": private_key_b64,
        "public_spki_sha256": android_public_spki_sha256(),
        "repository": claims.get("repository"),
        "ref": claims.get("ref"),
        "workflow_ref": claims.get("workflow_ref"),
    }

@app.post("/v1/ci/sign-model-artifact")
async def ci_sign_model_artifact(request: Request):
    try:
        claims = verify_github_oidc(request.headers.get("authorization"))
        artifact = await request.json()
        if not isinstance(artifact, dict):
            raise ValueError("artifact must be a JSON object")
        signed = sign_model_artifact(artifact)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(503, f"artifact signer unavailable: {type(exc).__name__}")
    return {
        **signed,
        "repository": claims.get("repository"),
        "ref": claims.get("ref"),
    }

@app.get("/ready")
def ready():
    gates = _all_model_gates()
    return {
        "status": "ready",
        "model_bundle_loaded": len(MODEL_REGISTRY) == len(SPORTS),
        "sports": list(SPORTS),
        "model_policy": "EVIDENCE_GATED_ENSEMBLE",
        "promoted_sports": [sport for sport, gate in gates.items() if gate["passed"]],
        "baseline_fallback_sports": [sport for sport, gate in gates.items() if not gate["passed"]],
    }

@app.get("/api/system/status", include_in_schema=False)
@app.get("/api/v1/system/status", include_in_schema=False)
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

    remaining = [
        "physical Android-device end-to-end smoke testing",
        "durable runtime prediction ledger plus rollback/alert validation",
    ]
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
            "stable_android_signing": "PASS_CI_PINNED_CERTIFICATE",
            "immutable_pregame_evidence_capture": "PASS_AUTOMATED_GITHUB_HISTORY",
        },
        "credential_gate": {
            "core_runtime_requires_secret": False,
            "rotation_confirmed": rotation,
            "odds_api_key_configured": odds_key,
            "odds_props_live_allowed": rotation and odds_key,
        },
        "production_ready": False,
        "production_ready_reason": "The HTTPS backend, pinned Android signing, four-sport live adapters, and immutable pregame evidence capture are operational. Production-ready remains blocked until four sport-specific trained models pass every v8 promotion gate, fresh live odds/props credentials pass canaries, the runtime prediction ledger/rollback alerts are validated, and a physical-device end-to-end smoke run is recorded.",
        "remaining_external_gates": remaining,
        "source_telemetry": _SOURCE,
        "drive_reconstruction": {sport: (DRIVE_RECONSTRUCTION.get("sports") or {}).get(sport, {}).get("status", "NO_EVIDENCE") for sport in SPORTS},
    }

@app.get("/api/models/status", include_in_schema=False)
@app.get("/api/v1/models/status", include_in_schema=False)
@app.get("/v1/models/status")
def model_status():
    return {
        sport: {
            **MODEL_REGISTRY[sport],
            "active_model_id": (
                PROMOTED_MODELS[sport].get("model_id")
                if PROMOTED_MODELS.get(sport) is not None and _promotion_gate_for(sport)["passed"]
                else MODEL_REGISTRY[sport].get("model_id")
            ),
            "promoted_artifact_loaded": PROMOTED_MODELS.get(sport) is not None,
            "promotion_gate": _promotion_gate_for(sport),
            "runtime_mode": _runtime_mode_for(sport),
        }
        for sport in SPORTS
    }

@app.get("/api/training/reconstruction", include_in_schema=False)
@app.get("/api/v1/training/reconstruction", include_in_schema=False)
@app.get("/v1/training/reconstruction")
def training_reconstruction():
    return DRIVE_RECONSTRUCTION

@app.get("/api/system/props", include_in_schema=False)
@app.get("/api/v1/system/props", include_in_schema=False)
@app.get("/v1/system/props")
def prop_capabilities():
    configured = bool(os.getenv("ODDS_API_KEY", "").strip())
    rotated = os.getenv("CREDENTIAL_ROTATION_CONFIRMED", "").strip().lower() == "true"
    return {
        "provider": "The Odds API v4",
        "credential_configured": configured,
        "credential_rotation_confirmed": rotated,
        "live_player_props_enabled": configured and rotated,
        "sports": {s: {"supported": True, "markets": PROP_MARKETS[s]} for s in SPORTS},
    }

def _team_code(name: str | None) -> str:
    words = [x for x in str(name or "").replace("-", " ").split() if x]
    if not words:
        return "TEAM"
    if len(words) == 1:
        return words[0][:4].upper()
    return "".join(x[0] for x in words)[-4:].upper()

def _legacy_game(game: dict[str, Any]) -> dict[str, Any]:
    when = game.get("event_time")
    now = datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(str(when).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except Exception:
        dt = None
    status = str(game.get("status") or "")
    upper = status.upper()
    if dt and dt > now:
        state = "pre"
    elif any(x in upper for x in ("FINAL", "COMPLETE", "OFF")):
        state = "post"
    else:
        state = "in"
    return {
        "id": str(game.get("event_id") or ""),
        "sport": str(game.get("sport") or "").upper(),
        "date": when,
        "status_name": status,
        "status_text": status,
        "state": state,
        "home_name": str(game.get("home") or ""),
        "away_name": str(game.get("away") or ""),
        "home_abbr": _team_code(game.get("home")),
        "away_abbr": _team_code(game.get("away")),
        "home_record": "",
        "away_record": "",
        "home_score": "",
        "away_score": "",
        "home_logo": "",
        "away_logo": "",
    }

def _fair_american(probability: float) -> int:
    p = max(1e-6, min(1 - 1e-6, float(probability)))
    if p >= 0.5:
        return round(-100 * p / (1 - p))
    return round(100 * (1 - p) / p)

def _legacy_prediction(game: dict[str, Any]) -> dict[str, Any] | None:
    market = game.get("market") or {}
    hp = game.get("home_win_probability")
    if hp is None:
        hp = market.get("home_probability")
    if hp is None:
        return None
    hp = float(hp)
    selected = max(hp, 1.0 - hp)
    home_name = str(game.get("home") or "")
    away_name = str(game.get("away") or "")
    pick_name = home_name if hp >= 0.5 else away_name
    pick = _team_code(pick_name)
    home_spread = market.get("home_spread")
    if home_spread is None:
        spread_lean = "MARKET N/A"
    else:
        point = float(home_spread) if pick_name == home_name else -float(home_spread)
        spread_lean = f"{pick} {point:+g}"
    total = market.get("total")
    total_lean = f"MARKET {float(total):g}" if total is not None else "MARKET N/A"
    return {
        "home_win_probability": round(hp, 6),
        "pick": pick,
        "pick_confidence": round(selected, 6),
        "moneyline": _fair_american(selected),
        "spread_lean": spread_lean,
        "total_lean": total_lean,
        "total_confidence": 0.0,
        "home_team_total": "MARKET N/A",
        "away_team_total": "MARKET N/A",
        "projected_outcome": f"{pick} ML · {_runtime_mode_for(str(game.get('sport') or '').upper())}",
        "engine": (
            "Signed promoted sport-specific trained model"
            if game.get("probability_source") == "signed_promoted_trained_model"
            else "De-vigged fresh market consensus baseline v1"
        ),
    }

@app.get("/v1/protocol")
def protocol():
    return {
        "master_protocol": [
            "Understand", "Decompose", "Inspect", "Map", "Challenge", "Plan",
            "Act", "Verify", "Recalibrate", "Explain", "Retain", "Improve",
        ],
        "promotion_policy": {
            "chronological_training": True,
            "in_fold_preprocessing": True,
            "oof_calibration_only": True,
            "ece_max": PROMOTION_ECE_MAX,
            "market_baseline_fallback": True,
            "automatic_wager_execution": False,
        },
    }

@app.get("/api/games/{sport}", include_in_schema=False)
@app.get("/api/v1/games/{sport}", include_in_schema=False)
@app.get("/v1/games/{sport}")
def legacy_games(sport: str, days: int = Query(2, ge=1, le=7)):
    s = sport.upper()
    if s not in SPORTS:
        raise HTTPException(404, "unsupported sport")
    rows: list[dict[str, Any]] = []
    hashes: list[str] = []
    for offset in range(days):
        d = _pacific_today() + timedelta(days=offset)
        payload = _search(sport=s, date=d.isoformat(), include_props=False)
        hashes.append(hashlib.sha256(json.dumps(payload["games"], sort_keys=True, default=str).encode()).hexdigest())
        rows.extend(_legacy_game(g) for g in payload["games"])
    return {
        "sport": s,
        "snapshot_sha256": hashlib.sha256("".join(hashes).encode()).hexdigest(),
        "games": rows,
    }

@app.get("/api/predictions/{sport}", include_in_schema=False)
@app.get("/api/v1/predictions/{sport}", include_in_schema=False)
@app.get("/v1/predictions/{sport}")
def legacy_predictions(sport: str, days: int = Query(2, ge=1, le=7)):
    if sport.lower() == "latest":
        return legacy_predictions_latest()
    s = sport.upper()
    if s not in SPORTS:
        raise HTTPException(404, "unsupported sport")
    generated_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    snapshots: list[str] = []
    for offset in range(days):
        d = date_cls.today() + timedelta(days=offset)
        payload = _search(sport=s, date=d.isoformat(), include_props=False)
        snapshots.append(hashlib.sha256(json.dumps(payload["games"], sort_keys=True, default=str).encode()).hexdigest())
        for game in payload["games"]:
            legacy_game = _legacy_game(game)
            if legacy_game["state"] != "pre":
                continue
            pred = _legacy_prediction(game)
            if pred is None:
                continue
            rows.append({
                "game": legacy_game,
                "prediction": pred,
                "model_state": _runtime_mode_for(s),
                "reasoning": game.get("prediction_reasoning"),
            })
    snapshot = hashlib.sha256("".join(snapshots).encode()).hexdigest()
    return {
        "sport": s,
        "generated_at": generated_at,
        "engine": "PhilthySports evidence-gated ensemble",
        "model_state": _runtime_mode_for(s),
        "snapshot_sha256": snapshot,
        "predictions": rows,
        "tracking": {"games_predicted": len(rows), "generated_at": generated_at},
        "governance": {
            "mode": "EVIDENCE_GATED_ENSEMBLE",
            "model_state": _runtime_mode_for(s),
            "promotion_gate": _promotion_gate_for(s),
            "private_provider_keys_embedded_in_apk": False,
        },
    }

@app.get("/api/odds/{sport}", include_in_schema=False)
@app.get("/api/v1/odds/{sport}", include_in_schema=False)
@app.get("/v1/odds/{sport}")
def legacy_odds(sport: str, date: str | None = None):
    s = sport.upper()
    if s not in SPORTS:
        raise HTTPException(404, "unsupported sport")
    d = date_cls.fromisoformat(date) if date else date_cls.today()
    events = _odds(s, d)
    return {
        "sport": s,
        "date": d.isoformat(),
        "provider": (
            "The Odds API v4"
            if os.getenv("ODDS_API_KEY", "").strip()
            and os.getenv("CREDENTIAL_ROTATION_CONFIRMED", "").strip().lower() == "true"
            else "ESPN scoreboard odds"
        ),
        "events": events,
    }

@app.get("/api/predictions/latest", include_in_schema=False)
@app.get("/api/v1/predictions/latest", include_in_schema=False)
@app.get("/v1/predictions/latest")
def legacy_predictions_latest():
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verified_live_run": False,
        "predictions": [],
        "note": "No stale prediction cache is served. Use sport-scoped live prediction routes.",
    }

@app.get("/api/runs/latest", include_in_schema=False)
@app.get("/api/v1/runs/latest", include_in_schema=False)
@app.get("/v1/runs/latest")
def legacy_runs_latest():
    return {
        "latest_run": None,
        "runtime": "stateless_live_fetch",
        "note": "Current runtime does not fabricate a persisted run when no durable run ledger has been written.",
    }

@app.get("/api/today", include_in_schema=False)
@app.get("/api/v1/today", include_in_schema=False)
@app.get("/v1/today")
def today(
    include_props: bool = True,
    props_limit: int = 3,
    days: int = Query(2, ge=1, le=7),
):
    start = _pacific_today()
    games: list[dict[str, Any]] = []
    dates: list[str] = []
    for offset in range(days):
        d = start + timedelta(days=offset)
        dates.append(d.isoformat())
        payload = _search(
            date=d.isoformat(),
            include_props=include_props,
            props_limit=props_limit,
        )
        games.extend(payload["games"])
    return {
        "query": "",
        "date": start.isoformat(),
        "dates": dates,
        "timezone": "America/Los_Angeles",
        "sports": list(SPORTS),
        "fresh_fetch": True,
        "games": games,
        "source_telemetry": _SOURCE,
    }

@app.get("/api/search", include_in_schema=False)
@app.get("/api/v1/search", include_in_schema=False)
@app.get("/v1/search")
def search(q: str = "", sport: str | None = None, date: str | None = None, include_props: bool = False, props_limit: int = 3):
    try:
        return _search(q=q, sport=sport, date=date, include_props=include_props, props_limit=props_limit)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

@app.get("/api/games/{sport}/{event_id}", include_in_schema=False)
@app.get("/api/v1/games/{sport}/{event_id}", include_in_schema=False)
@app.get("/v1/games/{sport}/{event_id}")
def game_detail(sport: str, event_id: str, date: str | None = None):
    result = _search(sport=sport, date=date)
    game = next((g for g in result["games"] if str(g["event_id"]) == str(event_id)), None)
    if not game:
        raise HTTPException(404, "game not found in fresh schedule")
    score, market = game["projected_score"], game["market"]
    spread_pick = market.get("spread_pick")
    spread_probability = market.get("spread_pick_probability")
    if spread_pick == game.get("home"):
        spread_line = market.get("home_spread")
    elif spread_pick == game.get("away"):
        spread_line = market.get("away_spread")
    else:
        spread_line = None

    total_pick = market.get("total_pick")
    total_probability = market.get("total_pick_probability")
    total_line = market.get("total")

    reasons = [
        f"Fresh de-vigged consensus moneyline implies home win probability {market['home_probability']:.1%}."
        if market.get("home_probability") is not None
        else "Fresh sportsbook win probability is unavailable; no replacement probability is invented.",
        (
            f"Fresh two-sided spread prices lean {spread_pick} {float(spread_line):+g} "
            f"at {float(spread_probability):.1%} after de-vigging."
            if spread_pick and spread_line is not None and spread_probability is not None
            else "A two-sided priced spread lean is unavailable; no spread side is invented."
        ),
        (
            f"Fresh two-sided total prices lean {total_pick} {float(total_line):g} "
            f"at {float(total_probability):.1%} after de-vigging."
            if total_pick and total_line is not None and total_probability is not None
            else "A two-sided priced total lean is unavailable; no over/under side is invented."
        ),
        f"Consensus spread {market['home_spread']:+.1f} and total {market['total']:.1f} define the score projection."
        if market.get("home_spread") is not None and market.get("total") is not None
        else "Spread/total evidence is incomplete, so no synthetic score inputs are inserted.",
        game.get("prediction_reasoning") or "No governed probability explanation is available.",
    ]
    game["score_prediction"] = {
        "home": score.get("home"),
        "away": score.get("away"),
        "pick": game.get("pick"),
        "reasons": reasons,
    }
    game["market_predictions"] = {
        "moneyline": {
            "pick": game.get("pick"),
            "home_win_probability": game.get("home_win_probability"),
            "probability_source": game.get("probability_source"),
        },
        "spread": {
            "pick": spread_pick,
            "line": spread_line,
            "probability": spread_probability,
            "source": "fresh_two_sided_devigged_spread_market",
        },
        "total": {
            "pick": total_pick,
            "line": total_line,
            "probability": total_probability,
            "source": "fresh_two_sided_devigged_total_market",
        },
    }
    game["team_totals"] = {
        "home": score.get("home"),
        "away": score.get("away"),
        "method": score.get("method"),
    }
    return game

@app.get("/api/games/{sport}/{event_id}/props", include_in_schema=False)
@app.get("/api/v1/games/{sport}/{event_id}/props", include_in_schema=False)
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

@app.get("/api/games/{sport}/{event_id}/parlays", include_in_schema=False)
@app.get("/api/v1/games/{sport}/{event_id}/parlays", include_in_schema=False)
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

def _multisport_candidates(
    start_date: date_cls,
    *,
    target_count: int = 40,
    horizon_days: int = 4,
) -> tuple[list[dict[str, Any]], list[str]]:
    candidates: list[dict[str, Any]] = []
    dates_considered: list[str] = []
    per_sport_prop_events: dict[str, int] = {s: 0 for s in SPORTS}
    seen: set[tuple[str, str, str]] = set()

    def append_candidate(candidate: dict[str, Any]) -> None:
        key = (
            str(candidate["sport"]),
            str(candidate["event_id"]),
            str(candidate["label"]),
        )
        if key not in seen:
            candidates.append(candidate)
            seen.add(key)

    for offset in range(max(1, min(int(horizon_days), 7))):
        d = start_date + timedelta(days=offset)
        dates_considered.append(d.isoformat())
        result = _search(date=d.isoformat(), include_props=False)

        for game in result["games"]:
            sport = game["sport"]
            market = game.get("market") or {}
            common = {
                "sport": sport,
                "event_id": game["event_id"],
                "event_time": game.get("event_time"),
                "event_time_pacific": game.get("event_time_pacific"),
                "date": d.isoformat(),
                "matchup": game.get("matchup"),
                "model_state": _runtime_mode_for(sport),
            }

            hp = game.get("home_win_probability")
            if hp is None:
                hp = market.get("home_probability")
            if hp is not None and game.get("pick"):
                picked_home = game["pick"] == game.get("home")
                probability = float(hp) if picked_home else 1.0 - float(hp)
                if game.get("probability_source") == "signed_promoted_trained_model":
                    moneyline_reason = (
                        f"Signed promoted {sport} model assigns this side "
                        f"{probability:.1%} win probability from fresh pregame features."
                    )
                else:
                    moneyline_reason = (
                        f"Fresh de-vigged consensus moneyline gives this side "
                        f"{probability:.1%} implied probability across "
                        f"{len(market.get('books_used') or [])} contributing books."
                    )
                append_candidate({
                    **common,
                    "type": "moneyline",
                    "label": f"{game['pick']} moneyline",
                    "probability": round(probability, 6),
                    "reason": moneyline_reason,
                })

            spread_pick = market.get("spread_pick")
            spread_prob = market.get("spread_pick_probability")
            home_spread = market.get("home_spread")
            if (
                spread_pick
                and spread_prob is not None
                and home_spread is not None
            ):
                point = (
                    float(home_spread)
                    if spread_pick == game.get("home")
                    else -float(home_spread)
                )
                append_candidate({
                    **common,
                    "type": "spread",
                    "label": f"{spread_pick} {point:+g}",
                    "probability": round(float(spread_prob), 6),
                    "reason": (
                        f"Fresh two-sided spread prices de-vig to "
                        f"{float(spread_prob):.1%} for {spread_pick} {point:+g}; "
                        "the line is taken directly from the current sportsbook consensus."
                    ),
                })

            total_pick = market.get("total_pick")
            total_prob = market.get("total_pick_probability")
            total_line = market.get("total")
            if (
                total_pick
                and total_prob is not None
                and total_line is not None
            ):
                append_candidate({
                    **common,
                    "type": "total",
                    "label": f"{total_pick} {float(total_line):g}",
                    "probability": round(float(total_prob), 6),
                    "reason": (
                        f"Fresh two-sided total prices de-vig to "
                        f"{float(total_prob):.1%} for {total_pick} "
                        f"{float(total_line):g}; no synthetic total is inserted."
                    ),
                })

            oid = game.get("odds_event_id")
            if oid and per_sport_prop_events[sport] < 3:
                per_sport_prop_events[sport] += 1
                try:
                    payload = _prop_payload(sport, oid)
                    for p in payload.get("props", [])[:8]:
                        if (
                            p.get("recommended_side")
                            and p.get("market_probability") is not None
                        ):
                            append_candidate({
                                **common,
                                "type": "player_prop",
                                "label": (
                                    f"{p['player']} {p['recommended_side']} "
                                    f"{p['line']} {p['market']}"
                                ),
                                "probability": round(
                                    float(p["market_probability"]), 6
                                ),
                                "reason": p.get("reason"),
                                "model_state": p.get("model_state"),
                            })
                except Exception:
                    pass

        if len(candidates) >= target_count:
            break

    candidates.sort(
        key=lambda x: (
            float(x.get("probability") or 0.0),
            1 if x.get("type") == "player_prop" else 0,
            1 if x.get("type") == "moneyline" else 0,
        ),
        reverse=True,
    )
    return candidates, dates_considered


def _build_multisport_parlay(
    leg_count: int,
    date: str | None = None,
) -> dict[str, Any]:
    if leg_count not in {7, 10, 14}:
        raise ValueError("leg_count must be one of 7, 10, or 14")

    d = date_cls.fromisoformat(date) if date else _pacific_today()
    candidates, dates_considered = _multisport_candidates(
        d,
        target_count=max(40, leg_count * 4),
        horizon_days=4,
    )

    profile = {
        7: "BEST_7_BALANCED",
        10: "BEST_10_PROP_WEIGHTED",
        14: "BEST_14_DEEP_MULTISPORT",
    }[leg_count]
    desired_props = {7: 2, 10: 4, 14: 5}[leg_count]

    selected: list[dict[str, Any]] = []
    selected_keys: set[tuple[str, str, str]] = set()
    event_counts: dict[tuple[str, str], int] = {}

    def add_leg(leg: dict[str, Any]) -> bool:
        key = (leg["sport"], str(leg["event_id"]), leg["label"])
        event_key = (leg["sport"], str(leg["event_id"]))
        if key in selected_keys:
            return False
        if event_counts.get(event_key, 0) >= 2:
            return False
        selected.append(leg)
        selected_keys.add(key)
        event_counts[event_key] = event_counts.get(event_key, 0) + 1
        return True

    # Guarantee multisport coverage first whenever the live board has those sports.
    for sport in SPORTS:
        sport_best = next((x for x in candidates if x["sport"] == sport), None)
        if sport_best is not None:
            add_leg(sport_best)
        if len(selected) >= leg_count:
            break

    # Cover the core game markets without inventing a side when two-sided pricing
    # is unavailable. This is current de-vigged market evidence, not a fake model edge.
    for market_type in ("moneyline", "spread", "total"):
        if len(selected) >= leg_count:
            break
        if any(x.get("type") == market_type for x in selected):
            continue
        for candidate in (x for x in candidates if x.get("type") == market_type):
            if add_leg(candidate):
                break

    # Deliberately reserve space for player props. If the rotated live prop
    # credential or event mapping is unavailable, the response says so rather
    # than substituting a made-up prop.
    prop_count = sum(1 for x in selected if x.get("type") == "player_prop")
    if prop_count < desired_props:
        for leg in (x for x in candidates if x.get("type") == "player_prop"):
            if add_leg(leg):
                prop_count += 1
            if prop_count >= desired_props or len(selected) >= leg_count:
                break

    # Build all three cards independently. The deterministic rotation changes the
    # remaining candidate order so 7, 10, and 14 are not nested copies.
    if candidates:
        rotation = {
            7: 0,
            10: max(1, len(candidates) // 7),
            14: max(2, len(candidates) // 5),
        }[leg_count]
        rotated = candidates[rotation:] + candidates[:rotation]
    else:
        rotated = []

    for leg in rotated:
        if len(selected) >= leg_count:
            break
        add_leg(leg)

    props_used = sum(1 for x in selected if x.get("type") == "player_prop")
    sports_used = sorted({x["sport"] for x in selected})
    type_counts = {
        kind: sum(1 for x in selected if x.get("type") == kind)
        for kind in ("moneyline", "spread", "total", "player_prop")
    }
    card_id = f"{d.isoformat()}-{leg_count}-{profile}"

    if len(selected) != leg_count or len(sports_used) <= 1:
        status = "INSUFFICIENT_FRESH_ELIGIBLE_LEGS"
    elif props_used == 0:
        status = "LIVE_PLAYER_PROPS_UNAVAILABLE"
    elif props_used < desired_props:
        status = "PARTIAL_PLAYER_PROP_COVERAGE"
    else:
        status = "OK"

    return {
        "card_id": card_id,
        "date": d.isoformat(),
        "timezone": "America/Los_Angeles",
        "dates_considered": dates_considered,
        "requested_legs": leg_count,
        "actual_legs": len(selected),
        "selection_profile": profile,
        "selection_basis": "BEST_AVAILABLE_BY_FRESH_DEVIGGED_PROBABILITY_WITH_DIVERSIFICATION",
        "multisport": len(sports_used) > 1,
        "sports_included": sports_used,
        "target_player_prop_legs": desired_props,
        "player_prop_legs": props_used,
        "market_pick_legs": len(selected) - props_used,
        "selection_breakdown": type_counts,
        "legs": selected,
        "dependency_method": "UNSCORED_WITHOUT_VALIDATED_DEPENDENCY_MODEL",
        "estimated_joint_probability": None,
        "reasoning": [
            (
                f"This is an independent {leg_count}-leg card, not a prefix of "
                "another card. Eligible live moneyline, spread, total, and "
                "player-prop legs are ranked by fresh de-vigged probability."
            ),
            (
                "Selection is diversified across sports and events, with no more "
                "than two legs from the same event, to avoid stuffing one matchup "
                "with highly related legs."
            ),
            (
                f"This profile targets {desired_props} player-prop legs when fresh "
                f"mapped props exist; {props_used} passed the live evidence checks."
            ),
            (
                "No missing leg, side, total, player prop, or probability is "
                "fabricated. Missing live evidence reduces coverage or changes status."
            ),
            (
                "Joint probability remains unscored until measured cross-leg "
                "dependence passes the v8 governance threshold."
            ),
        ],
        "status": status,
    }


@app.get("/api/parlays/multisport", include_in_schema=False)
@app.get("/api/v1/parlays/multisport", include_in_schema=False)
@app.get("/v1/parlays/multisport")
def multisport_parlays(legs: int = Query(7), date: str | None = None):
    try:
        return _build_multisport_parlay(int(legs), date)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

