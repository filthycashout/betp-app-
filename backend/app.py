from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date as date_cls, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo
from market_validation import parse_props, parse_game_market, utc_time
from keyless_sportsbook import (
    keyless_game_events,
    keyless_prop_events,
    keyless_sportsbook_status,
)
from public_context import game_weather_context, sports_news, weather_context
from odds_api_net import (
    configured as odds_api_net_configured,
    events_for_date as odds_api_net_events_for_date,
    status as odds_api_net_status,
)

import requests
from provider_canary import live_provider_canaries
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

APP_VERSION = "1.6.7"
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
        "player_assists", "player_defensive_interceptions", "player_field_goals",
        "player_kicking_points", "player_pass_longest_completion",
        "player_pass_rush_yds", "player_pass_rush_reception_tds",
        "player_pass_rush_reception_yds", "player_pass_yds_q1", "player_pats",
        "player_reception_longest", "player_rush_longest",
        "player_rush_reception_tds", "player_rush_reception_yds",
        "player_sacks", "player_solo_tackles", "player_tackles_assists",
        "player_tds_over", "player_tds", "player_1st_td", "player_last_td",
    ],
    "NBA": [
        "player_points", "player_rebounds", "player_assists", "player_threes",
        "player_blocks", "player_steals", "player_turnovers",
        "player_points_rebounds_assists", "player_points_rebounds",
        "player_points_assists", "player_rebounds_assists", "player_double_double",
        "player_triple_double", "player_points_q1", "player_rebounds_q1",
        "player_assists_q1", "player_blocks_steals", "player_field_goals",
        "player_frees_made", "player_frees_attempts", "player_first_basket",
        "player_first_team_basket", "player_method_of_first_basket",
        "player_fantasy_points",
    ],
    "MLB": [
        "batter_hits", "batter_home_runs", "batter_total_bases", "batter_rbis",
        "batter_runs_scored", "batter_hits_runs_rbis", "batter_walks",
        "batter_strikeouts", "batter_stolen_bases", "pitcher_strikeouts",
        "pitcher_hits_allowed", "pitcher_walks", "pitcher_earned_runs", "pitcher_outs",
        "batter_first_home_run", "batter_singles", "batter_doubles",
        "batter_triples", "batter_fantasy_score", "pitcher_record_a_win",
    ],
    "NHL": [
        "player_points", "player_power_play_points", "player_assists",
        "player_blocked_shots", "player_shots_on_goal", "player_goals",
        "player_total_saves", "player_goal_scorer_anytime",
        "player_goal_scorer_first", "player_goal_scorer_last",
    ],
}

PROP_ALTERNATE_MARKETS = {
    "NFL": [
        "player_assists_alternate", "player_field_goals_alternate",
        "player_kicking_points_alternate", "player_pass_attempts_alternate",
        "player_pass_completions_alternate", "player_pass_interceptions_alternate",
        "player_pass_longest_completion_alternate", "player_pass_rush_yds_alternate",
        "player_pass_rush_reception_tds_alternate",
        "player_pass_rush_reception_yds_alternate", "player_pass_tds_alternate",
        "player_pass_yds_alternate", "player_pats_alternate",
        "player_receptions_alternate", "player_reception_longest_alternate",
        "player_reception_tds_alternate", "player_reception_yds_alternate",
        "player_rush_attempts_alternate", "player_rush_longest_alternate",
        "player_rush_reception_tds_alternate", "player_rush_reception_yds_alternate",
        "player_rush_tds_alternate", "player_rush_yds_alternate",
        "player_sacks_alternate", "player_solo_tackles_alternate",
        "player_tackles_assists_alternate",
    ],
    "NBA": [
        "player_points_alternate", "player_rebounds_alternate",
        "player_assists_alternate", "player_blocks_alternate",
        "player_steals_alternate", "player_turnovers_alternate",
        "player_threes_alternate", "player_points_assists_alternate",
        "player_points_rebounds_alternate", "player_rebounds_assists_alternate",
        "player_points_rebounds_assists_alternate", "player_fantasy_points_alternate",
    ],
    "MLB": [
        "batter_total_bases_alternate", "batter_home_runs_alternate",
        "batter_hits_alternate", "batter_rbis_alternate", "batter_walks_alternate",
        "batter_strikeouts_alternate", "batter_runs_scored_alternate",
        "batter_hits_runs_rbis_alternate", "batter_singles_alternate",
        "batter_doubles_alternate", "batter_triples_alternate",
        "batter_fantasy_score_alternate", "pitcher_hits_allowed_alternate",
        "pitcher_walks_alternate", "pitcher_earned_runs_alternate",
        "pitcher_strikeouts_alternate", "pitcher_outs_alternate",
    ],
    "NHL": [
        "player_points_alternate", "player_assists_alternate",
        "player_power_play_points_alternate", "player_goals_alternate",
        "player_shots_on_goal_alternate", "player_blocked_shots_alternate",
        "player_total_saves_alternate",
    ],
}

# Default live pulls stay intentionally narrower to protect quota and latency.
# Standard and alternate catalogs remain discoverable through /v1/system/props,
# and callers may request any supported subset explicitly.
PROP_DEFAULT_LIVE_MARKETS = {
    "NFL": [
        "player_pass_yds", "player_rush_yds", "player_reception_yds",
        "player_pass_tds", "player_receptions", "player_pass_completions",
        "player_pass_attempts", "player_pass_interceptions", "player_rush_attempts",
        "player_pass_longest_completion", "player_pass_rush_yds",
        "player_pass_rush_reception_yds", "player_reception_longest",
        "player_rush_longest", "player_rush_reception_yds",
    ],
    "NBA": [
        "player_points", "player_rebounds", "player_assists", "player_threes",
        "player_blocks", "player_steals", "player_turnovers",
        "player_points_rebounds_assists", "player_points_rebounds",
        "player_points_assists", "player_rebounds_assists", "player_blocks_steals",
        "player_field_goals", "player_frees_made", "player_frees_attempts",
    ],
    "MLB": [
        "batter_hits", "batter_home_runs", "batter_total_bases", "batter_rbis",
        "batter_runs_scored", "batter_hits_runs_rbis", "batter_walks",
        "batter_strikeouts", "batter_stolen_bases", "batter_singles",
        "batter_doubles", "batter_triples", "pitcher_strikeouts",
        "pitcher_hits_allowed", "pitcher_walks", "pitcher_earned_runs", "pitcher_outs",
    ],
    "NHL": [
        "player_points", "player_power_play_points", "player_assists",
        "player_blocked_shots", "player_shots_on_goal", "player_goals",
        "player_total_saves",
    ],
}

MODEL_BUNDLE_PATH = Path(__file__).resolve().parent / "models" / "manifest.json"
DRIVE_RECONSTRUCTION_PATH = Path(__file__).resolve().parent / "training" / "drive_reconstruction_manifest.json"
DRIVE_RECONSTRUCTION_ADDENDUM_PATH = Path(__file__).resolve().parent / "training" / "drive_reconstruction_addendum_2026-10-02.json"
CANDIDATE_REGISTRY_PATH = Path(__file__).resolve().parent / "models" / "candidate_registry.json"
V8_GATE_STATUS_PATH = Path(__file__).resolve().parent / "evidence" / "v8_gate_status.json"

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

def _load_drive_reconstruction() -> dict[str, Any]:
    if not DRIVE_RECONSTRUCTION_PATH.exists():
        return {"status": "MISSING", "sports": {}}
    return json.loads(DRIVE_RECONSTRUCTION_PATH.read_text())

DRIVE_RECONSTRUCTION = _load_drive_reconstruction()


def _load_drive_reconstruction_addendum() -> dict[str, Any]:
    if not DRIVE_RECONSTRUCTION_ADDENDUM_PATH.exists():
        return {"status": "MISSING"}
    return json.loads(DRIVE_RECONSTRUCTION_ADDENDUM_PATH.read_text())


DRIVE_RECONSTRUCTION_ADDENDUM = _load_drive_reconstruction_addendum()


def _load_candidate_registry() -> dict[str, Any]:
    if not CANDIDATE_REGISTRY_PATH.exists():
        return {"registry_version": 1, "sports": {}}
    return json.loads(CANDIDATE_REGISTRY_PATH.read_text())


CANDIDATE_REGISTRY = _load_candidate_registry()


def _load_v8_gate_status() -> dict[str, Any]:
    if not V8_GATE_STATUS_PATH.exists():
        return {"schema_version": 1, "evidence_capture": {"verified": False}}
    try:
        payload = json.loads(V8_GATE_STATUS_PATH.read_text())
        return payload if isinstance(payload, dict) else {"schema_version": 1, "evidence_capture": {"verified": False}}
    except (OSError, ValueError, TypeError):
        return {"schema_version": 1, "evidence_capture": {"verified": False}}


V8_GATE_STATUS = _load_v8_gate_status()

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
    return (
        "PROMOTED_TRAINED_MODEL"
        if _promotion_gate_for(sport)["passed"]
        else "EVIDENCE_GATED_HYBRID_MARKET_FORM_FALLBACK"
    )

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

KEYLESS_LIVE_SOURCES = {
    "NFL": {
        "scoreboard": "ESPN Site API",
        "detail": "ESPN Site API summary",
        "github_evidence": [
            "sportsdataverse/sportsdataverse-js",
            "stylo-stack/ESPN-API-Documentation",
        ],
        "credential_required": False,
    },
    "NBA": {
        "scoreboard": "NBA CDN LiveData",
        "detail": "NBA CDN LiveData boxscore/play-by-play",
        "fallback": "ESPN Site API",
        "github_evidence": [
            "swar/nba_api",
            "sportsdataverse/sportsdataverse-py",
        ],
        "credential_required": False,
    },
    "MLB": {
        "scoreboard": "MLB StatsAPI",
        "detail": "MLB StatsAPI live feed",
        "github_evidence": [
            "toddrob99/MLB-StatsAPI",
            "sportsdataverse/sportsdataverse-js",
        ],
        "credential_required": False,
    },
    "NHL": {
        "scoreboard": "NHL Web API",
        "detail": "NHL Gamecenter landing/play-by-play",
        "github_evidence": [
            "coreyjs/nhl-api-py",
            "Zmalski/NHL-API-Reference",
        ],
        "credential_required": False,
    },
}

_LIVE_CACHE: dict[str, tuple[float, Any]] = {}


def _cached_json(
    cache_key: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    ttl_seconds: int = 15,
    timeout: int = 12,
) -> Any:
    now = time.time()
    cached = _LIVE_CACHE.get(cache_key)
    if cached and now - cached[0] <= ttl_seconds:
        return cached[1]
    value = _json(url, params=params, timeout=timeout)
    _LIVE_CACHE[cache_key] = (now, value)
    return value


def _espn_live_scoreboard(sport: str, d: date_cls) -> dict[str, Any]:
    a, b = ESPN[sport]
    raw = _cached_json(
        f"live:{sport}:espn:{d.isoformat()}",
        f"https://site.api.espn.com/apis/site/v2/sports/{a}/{b}/scoreboard",
        params={"dates": d.strftime("%Y%m%d"), "limit": 1000},
        ttl_seconds=15,
    )
    games = []
    for event in raw.get("events") or []:
        comp = (event.get("competitions") or [{}])[0]
        competitors = comp.get("competitors") or []
        home = next((x for x in competitors if x.get("homeAway") == "home"), {})
        away = next((x for x in competitors if x.get("homeAway") == "away"), {})
        status = (event.get("status") or {}).get("type") or {}
        games.append({
            "event_id": str(event.get("id") or ""),
            "sport": sport,
            "event_time": event.get("date") or comp.get("date"),
            "status": status.get("name") or status.get("description"),
            "state": status.get("state"),
            "completed": status.get("completed"),
            "period": (event.get("status") or {}).get("period"),
            "clock": (event.get("status") or {}).get("displayClock"),
            "home": (home.get("team") or {}).get("displayName"),
            "away": (away.get("team") or {}).get("displayName"),
            "home_score": _coerce_number(home.get("score")),
            "away_score": _coerce_number(away.get("score")),
        })
    return {
        "sport": sport,
        "provider": "ESPN Site API",
        "credential_required": False,
        "date": d.isoformat(),
        "games": games,
    }


def _nba_cdn_scoreboard() -> dict[str, Any]:
    raw = _cached_json(
        "live:NBA:cdn:today",
        "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json",
        ttl_seconds=10,
    )
    board = raw.get("scoreboard") or {}
    games = []
    for game in board.get("games") or []:
        home = game.get("homeTeam") or {}
        away = game.get("awayTeam") or {}
        games.append({
            "event_id": str(game.get("gameId") or ""),
            "sport": "NBA",
            "event_time": game.get("gameTimeUTC") or game.get("gameTimeLocal"),
            "status": game.get("gameStatusText"),
            "state": game.get("gameStatus"),
            "completed": game.get("gameStatus") == 3,
            "period": game.get("period"),
            "clock": game.get("gameClock"),
            "home": home.get("teamName") or home.get("teamTricode"),
            "away": away.get("teamName") or away.get("teamTricode"),
            "home_team_id": home.get("teamId"),
            "away_team_id": away.get("teamId"),
            "home_score": _coerce_number(home.get("score")),
            "away_score": _coerce_number(away.get("score")),
        })
    return {
        "sport": "NBA",
        "provider": "NBA CDN LiveData",
        "credential_required": False,
        "date": board.get("gameDate"),
        "games": games,
    }


def _mlb_live_scoreboard(d: date_cls) -> dict[str, Any]:
    raw = _cached_json(
        f"live:MLB:statsapi:{d.isoformat()}",
        "https://statsapi.mlb.com/api/v1/schedule",
        params={
            "sportId": 1,
            "date": d.isoformat(),
            "hydrate": "team,linescore,probablePitcher",
        },
        ttl_seconds=10,
    )
    games = []
    for day in raw.get("dates") or []:
        for game in day.get("games") or []:
            home = (game.get("teams") or {}).get("home") or {}
            away = (game.get("teams") or {}).get("away") or {}
            linescore = game.get("linescore") or {}
            games.append({
                "event_id": str(game.get("gamePk") or ""),
                "sport": "MLB",
                "event_time": game.get("gameDate"),
                "status": (game.get("status") or {}).get("detailedState"),
                "state": (game.get("status") or {}).get("abstractGameState"),
                "completed": (game.get("status") or {}).get("abstractGameState") == "Final",
                "period": linescore.get("currentInning"),
                "clock": linescore.get("inningState"),
                "home": ((home.get("team") or {}).get("name")),
                "away": ((away.get("team") or {}).get("name")),
                "home_score": _coerce_number(home.get("score")),
                "away_score": _coerce_number(away.get("score")),
                "home_probable_pitcher": (home.get("probablePitcher") or {}).get("fullName"),
                "away_probable_pitcher": (away.get("probablePitcher") or {}).get("fullName"),
            })
    return {
        "sport": "MLB",
        "provider": "MLB StatsAPI",
        "credential_required": False,
        "date": d.isoformat(),
        "games": games,
    }


def _nhl_live_scoreboard(d: date_cls) -> dict[str, Any]:
    raw = _cached_json(
        f"live:NHL:web:{d.isoformat()}",
        f"https://api-web.nhle.com/v1/schedule/{d.isoformat()}",
        ttl_seconds=10,
    )
    games = []
    for day in raw.get("gameWeek") or []:
        if day.get("date") != d.isoformat():
            continue
        for game in day.get("games") or []:
            home = game.get("homeTeam") or {}
            away = game.get("awayTeam") or {}
            clock = game.get("clock") or {}
            period = game.get("periodDescriptor") or {}
            games.append({
                "event_id": str(game.get("id") or ""),
                "sport": "NHL",
                "event_time": game.get("startTimeUTC"),
                "status": game.get("gameState"),
                "state": game.get("gameState"),
                "completed": str(game.get("gameState") or "").upper() in {"FINAL", "OFF"},
                "period": period.get("number"),
                "clock": clock.get("timeRemaining"),
                "home": _nhl_name(home),
                "away": _nhl_name(away),
                "home_score": _coerce_number(home.get("score")),
                "away_score": _coerce_number(away.get("score")),
            })
    return {
        "sport": "NHL",
        "provider": "NHL Web API",
        "credential_required": False,
        "date": d.isoformat(),
        "games": games,
    }


def _keyless_live_scoreboard(sport: str, d: date_cls) -> dict[str, Any]:
    s = sport.upper()
    if s == "NBA" and d == _pacific_today():
        try:
            return _timed("NBA.live.nba_cdn", _nba_cdn_scoreboard)
        except Exception:
            return _timed("NBA.live.espn_fallback", lambda: _espn_live_scoreboard("NBA", d))
    if s == "MLB":
        return _timed("MLB.live.statsapi", lambda: _mlb_live_scoreboard(d))
    if s == "NHL":
        return _timed("NHL.live.web", lambda: _nhl_live_scoreboard(d))
    if s in {"NFL", "NBA"}:
        return _timed(f"{s}.live.espn", lambda: _espn_live_scoreboard(s, d))
    raise ValueError(f"unsupported sport: {sport}")


def _keyless_live_game(sport: str, event_id: str) -> dict[str, Any]:
    s = sport.upper()
    if s == "NFL":
        payload = _timed(
            "NFL.live.summary",
            lambda: _cached_json(
                f"live:NFL:summary:{event_id}",
                "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary",
                params={"event": event_id},
                ttl_seconds=10,
            ),
        )
        return {
            "sport": s,
            "event_id": event_id,
            "provider": "ESPN Site API",
            "credential_required": False,
            "summary": payload,
        }

    if s == "NBA":
        try:
            box = _timed(
                "NBA.live.boxscore",
                lambda: _cached_json(
                    f"live:NBA:boxscore:{event_id}",
                    f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{event_id}.json",
                    ttl_seconds=8,
                ),
            )
            pbp = _timed(
                "NBA.live.playbyplay",
                lambda: _cached_json(
                    f"live:NBA:pbp:{event_id}",
                    f"https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{event_id}.json",
                    ttl_seconds=5,
                ),
            )
            return {
                "sport": s,
                "event_id": event_id,
                "provider": "NBA CDN LiveData",
                "credential_required": False,
                "boxscore": box,
                "play_by_play": pbp,
            }
        except Exception:
            payload = _timed(
                "NBA.live.espn_summary_fallback",
                lambda: _cached_json(
                    f"live:NBA:espn_summary:{event_id}",
                    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary",
                    params={"event": event_id},
                    ttl_seconds=10,
                ),
            )
            return {
                "sport": s,
                "event_id": event_id,
                "provider": "ESPN Site API fallback",
                "credential_required": False,
                "summary": payload,
            }

    if s == "MLB":
        payload = _timed(
            "MLB.live.feed",
            lambda: _cached_json(
                f"live:MLB:feed:{event_id}",
                f"https://statsapi.mlb.com/api/v1.1/game/{event_id}/feed/live",
                ttl_seconds=5,
            ),
        )
        return {
            "sport": s,
            "event_id": event_id,
            "provider": "MLB StatsAPI",
            "credential_required": False,
            "live_feed": payload,
        }

    if s == "NHL":
        landing = _timed(
            "NHL.live.landing",
            lambda: _cached_json(
                f"live:NHL:landing:{event_id}",
                f"https://api-web.nhle.com/v1/gamecenter/{event_id}/landing",
                ttl_seconds=8,
            ),
        )
        pbp = _timed(
            "NHL.live.playbyplay",
            lambda: _cached_json(
                f"live:NHL:pbp:{event_id}",
                f"https://api-web.nhle.com/v1/gamecenter/{event_id}/play-by-play",
                ttl_seconds=5,
            ),
        )
        return {
            "sport": s,
            "event_id": event_id,
            "provider": "NHL Web API",
            "credential_required": False,
            "landing": landing,
            "play_by_play": pbp,
        }

    raise ValueError(f"unsupported sport: {sport}")


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
        _SOURCE[name] = {"ok": False, "elapsed_ms": round((time.perf_counter()-started)*1000, 1), "checked_at": datetime.now(timezone.utc).isoformat(), "error": type(exc).__name__}
        raise

class ProviderError(RuntimeError):
    """Safe error: never includes a URL, query string, header or response body."""


def _json(url: str, *, params: dict | None = None, timeout: int = 10):
    for attempt in range(3):
        try:
            r = SESSION.get(url, params=params, timeout=(3, timeout))
            if r.status_code in {429, 502, 503, 504} and attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise ProviderError(f"Provider HTTP {r.status_code}")
            try:
                return r.json()
            except ValueError:
                raise ProviderError("Provider returned invalid JSON") from None
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 2:
                raise ProviderError("Provider network timeout or connection failure") from None
            time.sleep(0.5 * (attempt + 1))
        except requests.RequestException:
            raise ProviderError("Provider request failed") from None


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
            "home_record_pct": _competitor_record_pct(home),
            "away_record_pct": _competitor_record_pct(away),
            "status": ev.get("status", {}).get("type", {}).get("name", ""), "schedule_source": "ESPN",
        })
    return out

def _mlb_schedule(date_iso: str) -> list[dict]:
    raw = _json("https://statsapi.mlb.com/api/v1/schedule", params={"sportId": 1, "date": date_iso, "hydrate": "probablePitcher,team,venue(location,fieldInfo)"})
    out = []
    for day in raw.get("dates", []):
        for g in day.get("games", []):
            venue = g.get("venue") or {}
            coordinates = (venue.get("location") or {}).get("defaultCoordinates") or {}
            out.append({
                "event_id": str(g.get("gamePk")), "sport": "MLB", "event_time": g.get("gameDate"),
                "home": g["teams"]["home"]["team"]["name"], "away": g["teams"]["away"]["team"]["name"],
                "home_record_pct": _record_pct_mapping(g["teams"]["home"].get("leagueRecord") or {}),
                "away_record_pct": _record_pct_mapping(g["teams"]["away"].get("leagueRecord") or {}),
                "home_probable_pitcher": g["teams"]["home"].get("probablePitcher", {}).get("fullName"),
                "away_probable_pitcher": g["teams"]["away"].get("probablePitcher", {}).get("fullName"),
                "venue": {
                    "name": venue.get("name"), "latitude": coordinates.get("latitude"),
                    "longitude": coordinates.get("longitude"),
                    "outdoor": str((venue.get("fieldInfo") or {}).get("roofType") or "").lower() == "open",
                    "source": "MLB StatsAPI venue",
                },
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
                "home_record_pct": _record_pct_mapping(g.get("homeTeam") or {}),
                "away_record_pct": _record_pct_mapping(g.get("awayTeam") or {}),
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


def _record_pct_mapping(value: Any) -> float | None:
    if not isinstance(value, dict):
        return None
    for key in ("pct", "winPercent", "winPercentage", "pointPctg"):
        raw = value.get(key)
        if raw is not None:
            try:
                pct = float(raw)
                if pct > 1:
                    pct /= 100.0
                if 0 <= pct <= 1:
                    return pct
            except (TypeError, ValueError):
                pass
    wins = value.get("wins")
    losses = value.get("losses")
    ot = value.get("otLosses") or value.get("overtimeLosses") or 0
    try:
        w, l, o = float(wins), float(losses), float(ot)
        games = w + l + o
        if games > 0:
            return (w + 0.5 * o) / games
    except (TypeError, ValueError):
        return None
    return None


def _competitor_record_pct(competitor: dict[str, Any]) -> float | None:
    direct = _record_pct_mapping(competitor)
    if direct is not None:
        return direct
    for record in competitor.get("records") or []:
        if not isinstance(record, dict):
            continue
        stats = {
            str(item.get("name") or item.get("abbreviation") or ""): item.get("value")
            for item in (record.get("stats") or [])
            if isinstance(item, dict)
        }
        pct = _record_pct_mapping({
            "wins": stats.get("wins"),
            "losses": stats.get("losses"),
            "winPercent": stats.get("winPercent") or stats.get("winPercentage"),
        })
        if pct is not None:
            return pct
        summary = str(record.get("summary") or "").strip()
        if summary:
            parts = summary.replace("–", "-").split("-")
            try:
                nums = [float(x) for x in parts if x.strip() != ""]
                if len(nums) >= 2 and sum(nums[:2]) > 0:
                    return nums[0] / sum(nums[:2])
            except ValueError:
                pass
    return None


_FORM_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_FORM_TTL_SECONDS = 900
_FORM_LOOKBACK_DAYS = {"NFL": 120, "NBA": 45, "MLB": 35, "NHL": 45}


def _espn_recent_form_snapshot(sport: str, d: date_cls) -> dict[str, Any]:
    cache_key = (sport, d.isoformat())
    cached = _FORM_CACHE.get(cache_key)
    now = time.time()
    if cached and now - cached[0] <= _FORM_TTL_SECONDS:
        return cached[1]

    end = d - timedelta(days=1)
    start = end - timedelta(days=_FORM_LOOKBACK_DAYS[sport])
    if end < start:
        return {"teams": {}, "completed_games": 0, "league_mean_abs_margin": None}

    a, b = ESPN[sport]
    raw = _json(
        f"https://site.api.espn.com/apis/site/v2/sports/{a}/{b}/scoreboard",
        params={
            "dates": f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}",
            "limit": 1000,
            "lang": "en",
            "region": "us",
        },
        timeout=15,
    )
    teams: dict[str, dict[str, Any]] = {}
    margins: list[float] = []
    completed = 0

    for event in raw.get("events") or []:
        status = (event.get("status") or {}).get("type") or {}
        if status.get("completed") is not True and str(status.get("state") or "").lower() != "post":
            continue
        competitions = event.get("competitions") or []
        if not competitions or not isinstance(competitions[0], dict):
            continue
        competitors = competitions[0].get("competitors") or []
        home = next((x for x in competitors if isinstance(x, dict) and x.get("homeAway") == "home"), None)
        away = next((x for x in competitors if isinstance(x, dict) and x.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        hs = _coerce_number(home.get("score"))
        aw = _coerce_number(away.get("score"))
        if hs is None or aw is None:
            continue

        home_name = str((home.get("team") or {}).get("displayName") or (home.get("team") or {}).get("name") or "")
        away_name = str((away.get("team") or {}).get("displayName") or (away.get("team") or {}).get("name") or "")
        if not home_name or not away_name:
            continue

        completed += 1
        margins.append(abs(hs - aw))
        for name, scored, allowed, won in (
            (home_name, hs, aw, hs > aw),
            (away_name, aw, hs, aw > hs),
        ):
            key = _norm(name)
            row = teams.setdefault(
                key,
                {
                    "name": name,
                    "games": 0,
                    "wins": 0,
                    "ties": 0,
                    "points_for": 0.0,
                    "points_against": 0.0,
                },
            )
            row["games"] += 1
            row["points_for"] += float(scored)
            row["points_against"] += float(allowed)
            if scored == allowed:
                row["ties"] += 1
            elif won:
                row["wins"] += 1

    snapshot = {
        "teams": teams,
        "completed_games": completed,
        "league_mean_abs_margin": mean(margins) if margins else None,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
    }
    _FORM_CACHE[cache_key] = (now, snapshot)
    return snapshot


def _nhl_recent_form_snapshot(d: date_cls) -> dict[str, Any]:
    cache_key = ("NHL_OFFICIAL", d.isoformat())
    cached = _FORM_CACHE.get(cache_key)
    now = time.time()
    if cached and now - cached[0] <= _FORM_TTL_SECONDS:
        return cached[1]

    end = d - timedelta(days=1)
    start = end - timedelta(days=_FORM_LOOKBACK_DAYS["NHL"])
    teams: dict[str, dict[str, Any]] = {}
    margins: list[float] = []
    completed = 0
    seen: set[str] = set()
    cursor = start

    while cursor <= end:
        raw = _json(
            f"https://api-web.nhle.com/v1/schedule/{cursor.isoformat()}",
            timeout=12,
        )
        for day in raw.get("gameWeek") or []:
            day_raw = day.get("date")
            try:
                day_date = date_cls.fromisoformat(str(day_raw))
            except ValueError:
                continue
            if day_date < start or day_date > end:
                continue
            for game in day.get("games") or []:
                event_id = str(game.get("id") or "")
                if not event_id or event_id in seen:
                    continue
                seen.add(event_id)
                state = str(game.get("gameState") or "").upper()
                if state not in {"FINAL", "OFF"}:
                    continue
                home_obj = game.get("homeTeam") or {}
                away_obj = game.get("awayTeam") or {}
                hs = _coerce_number(home_obj.get("score"))
                aw = _coerce_number(away_obj.get("score"))
                home_name = _nhl_name(home_obj)
                away_name = _nhl_name(away_obj)
                if hs is None or aw is None or not home_name or not away_name:
                    continue

                completed += 1
                margins.append(abs(hs - aw))
                for name, scored, allowed, won in (
                    (home_name, hs, aw, hs > aw),
                    (away_name, aw, hs, aw > hs),
                ):
                    key = _norm(name)
                    row = teams.setdefault(
                        key,
                        {
                            "name": name,
                            "games": 0,
                            "wins": 0,
                            "ties": 0,
                            "points_for": 0.0,
                            "points_against": 0.0,
                        },
                    )
                    row["games"] += 1
                    row["points_for"] += float(scored)
                    row["points_against"] += float(allowed)
                    if scored == allowed:
                        row["ties"] += 1
                    elif won:
                        row["wins"] += 1
        cursor += timedelta(days=7)

    snapshot = {
        "teams": teams,
        "completed_games": completed,
        "league_mean_abs_margin": mean(margins) if margins else None,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "source": "NHL Web API completed schedules",
    }
    _FORM_CACHE[cache_key] = (now, snapshot)
    return snapshot


def _recent_form_snapshot(sport: str, d: date_cls) -> dict[str, Any]:
    if sport == "NHL":
        return _nhl_recent_form_snapshot(d)
    return _espn_recent_form_snapshot(sport, d)


def _form_team(snapshot: dict[str, Any], team_name: str | None) -> dict[str, Any] | None:
    wanted = _norm(team_name)
    if not wanted:
        return None
    teams = snapshot.get("teams") or {}
    if wanted in teams:
        return teams[wanted]
    for alias, row in teams.items():
        if alias and (wanted in alias or alias in wanted):
            return row
    return None


def _recent_form_prediction(
    sport: str,
    game: dict[str, Any],
    d: date_cls,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if snapshot is None:
        try:
            snapshot = _timed(
                f"{sport}.recent_form",
                lambda: _recent_form_snapshot(sport, d),
            )
        except Exception:
            snapshot = {"teams": {}}

    home = _form_team(snapshot, game.get("home"))
    away = _form_team(snapshot, game.get("away"))

    if home and away and int(home.get("games") or 0) > 0 and int(away.get("games") or 0) > 0:
        hg = float(home["games"])
        ag = float(away["games"])
        home_win = (float(home["wins"]) + 0.5 * float(home.get("ties") or 0) + 1.0) / (hg + 2.0)
        away_win = (float(away["wins"]) + 0.5 * float(away.get("ties") or 0) + 1.0) / (ag + 2.0)
        record_probability = (home_win + (1.0 - away_win)) / 2.0

        home_pf = float(home["points_for"]) / hg
        home_pa = float(home["points_against"]) / hg
        away_pf = float(away["points_for"]) / ag
        away_pa = float(away["points_against"]) / ag
        projected_home = (home_pf + away_pa) / 2.0
        projected_away = (away_pf + home_pa) / 2.0
        margin = projected_home - projected_away
        scale = float(snapshot.get("league_mean_abs_margin") or 1.0)
        scale = max(scale, 1.0)
        margin_probability = 1.0 / (1.0 + math.exp(-margin / scale))
        home_probability = max(
            0.10,
            min(0.90, 0.65 * record_probability + 0.35 * margin_probability),
        )
        return {
            "source": "keyless_recent_form_heuristic",
            "calibrated": False,
            "home_win_probability": round(home_probability, 6),
            "projected_score": {
                "home": round(max(0.0, projected_home), 1),
                "away": round(max(0.0, projected_away), 1),
                "method": "recent_completed_games_scoring_blend",
            },
            "home_recent_games": int(hg),
            "away_recent_games": int(ag),
            "window_start": snapshot.get("window_start"),
            "window_end": snapshot.get("window_end"),
            "note": (
                "Fallback uses only completed games before the matchup date. "
                "It is a transparent recent-form heuristic, not a calibrated promoted model."
            ),
        }

    home_pct = game.get("home_record_pct")
    away_pct = game.get("away_record_pct")
    if isinstance(home_pct, (int, float)) and isinstance(away_pct, (int, float)):
        p = max(0.10, min(0.90, (float(home_pct) + (1.0 - float(away_pct))) / 2.0))
        return {
            "source": "keyless_season_record_heuristic",
            "calibrated": False,
            "home_win_probability": round(p, 6),
            "projected_score": {"home": None, "away": None, "method": "unavailable_without_scoring_form"},
            "home_recent_games": None,
            "away_recent_games": None,
            "note": (
                "Fallback uses the current season records exposed by the official schedule feed. "
                "It is not a calibrated promoted model."
            ),
        }
    return None


def _prediction_bundle(
    game: dict[str, Any],
    market: dict[str, Any],
    score: dict[str, Any],
    hp: float | None,
    probability_source: str,
    reasoning: str,
    form: dict[str, Any] | None,
) -> dict[str, Any]:
    pick = None
    if hp is not None:
        pick = game.get("home") if float(hp) >= 0.5 else game.get("away")

    spread_pick = market.get("spread_pick")
    spread_line = None
    spread_probability = market.get("spread_pick_probability")
    spread_source = "fresh_two_sided_devigged_spread_market"
    home_spread = market.get("home_spread")

    predicted_home = score.get("home")
    predicted_away = score.get("away")
    if spread_pick == game.get("home"):
        spread_line = home_spread
    elif spread_pick == game.get("away") and home_spread is not None:
        spread_line = -float(home_spread)
    elif (
        spread_pick is None
        and home_spread is not None
        and predicted_home is not None
        and predicted_away is not None
    ):
        projected_margin = float(predicted_home) - float(predicted_away)
        cover_margin = projected_margin + float(home_spread)
        spread_pick = game.get("home") if cover_margin >= 0 else game.get("away")
        spread_line = float(home_spread) if spread_pick == game.get("home") else -float(home_spread)
        spread_probability = None
        spread_source = "recent_form_projection_vs_market_line"

    total_pick = market.get("total_pick")
    total_line = market.get("total")
    total_probability = market.get("total_pick_probability")
    total_source = "fresh_two_sided_devigged_total_market"
    projected_total = None
    if predicted_home is not None and predicted_away is not None:
        projected_total = round(float(predicted_home) + float(predicted_away), 1)
    if (
        total_pick is None
        and total_line is not None
        and projected_total is not None
    ):
        total_pick = "OVER" if projected_total >= float(total_line) else "UNDER"
        total_probability = None
        total_source = "recent_form_projection_vs_market_line"

    return {
        "generated": pick is not None,
        "moneyline": {
            "pick": pick,
            "home_win_probability": hp,
            "source": probability_source,
            "calibrated": probability_source == "signed_promoted_trained_model",
        },
        "spread": {
            "pick": spread_pick,
            "line": spread_line,
            "probability": spread_probability,
            "source": spread_source if spread_pick is not None else "unavailable",
        },
        "total": {
            "pick": total_pick,
            "line": total_line,
            "probability": total_probability,
            "projected_total": projected_total,
            "source": total_source if total_pick is not None else "unavailable",
        },
        "score": score,
        "reasoning": reasoning,
        "fallback": form,
    }


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
                "last_update": odds.get("lastUpdated") or odds.get("last_update"),
                "observed_at": now.isoformat(),
                "markets": markets,
            }],
            "data_quality": "PREGAME_KEYLESS",
            "market_source": "ESPN_SCOREBOARD_ODDS",
        })
    return events

def _odds(sport: str, d: date_cls) -> list[dict]:
    # No single sportsbook provider is allowed to make the Powerhouse board fail.
    # Credentialled providers are attempted independently, then keyless read-only
    # sources fill coverage. Every downstream pick still has to pass freshness and
    # two-sided evidence validation.
    events: list[dict[str, Any]] = []
    key = os.getenv("ODDS_API_KEY", "").strip()
    rotation = os.getenv("CREDENTIAL_ROTATION_CONFIRMED", "").strip().lower() == "true"

    if key and rotation:
        try:
            start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
            end = start + timedelta(hours=36)
            params = {
                "apiKey": key,
                "regions": "us",
                "markets": "h2h,spreads,totals",
                "oddsFormat": "american",
                "dateFormat": "iso",
                "commenceTimeFrom": start.isoformat().replace("+00:00", "Z"),
                "commenceTimeTo": end.isoformat().replace("+00:00", "Z"),
            }
            primary = _timed(
                f"{sport}.odds.the_odds_api",
                lambda: _json(
                    f"https://api.the-odds-api.com/v4/sports/{SPORT_KEYS[sport]}/odds/",
                    params=params,
                    timeout=12,
                ),
            )
            if isinstance(primary, list):
                events.extend(
                    {
                        **row,
                        "market_source": "THE_ODDS_API_V4",
                        "data_quality": "PREGAME_CREDENTIALLED",
                    }
                    for row in primary
                    if isinstance(row, dict)
                )
        except Exception:
            # Keep the board available through the next validated provider.
            pass

    if odds_api_net_configured():
        try:
            events.extend(
                _timed(
                    f"{sport}.odds.odds_api_net",
                    lambda: odds_api_net_events_for_date(sport, d),
                )
            )
        except Exception:
            pass

    try:
        direct = _timed(
            f"{sport}.odds.public_sportsbook_keyless",
            lambda: keyless_game_events(sport),
        )
    except Exception:
        direct = []
    try:
        espn = _timed(
            f"{sport}.odds.espn_keyless",
            lambda: _espn_market_events(sport, d),
        )
    except Exception:
        espn = []
    return [*events, *direct, *espn]

def _norm(s: str | None) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())

def _same_team(a: str | None, b: str | None) -> bool:
    x, y = _norm(a), _norm(b)
    return bool(x and y and (x == y or x in y or y in x))

def _market_source_rank(event: dict[str, Any]) -> int:
    source = str(event.get("market_source") or "").upper()
    if "THE_ODDS" in source:
        return 40
    if "ODDS_API_NET" in source:
        return 35
    if "BOVADA" in source:
        return 25
    if "DRAFTKINGS" in source:
        return 20
    if "FANDUEL" in source:
        return 20
    if "ESPN" in source:
        return 10
    return 0


def _match_odds(game: dict, events: list[dict]) -> dict | None:
    start = utc_time(game.get("event_time"))
    if start is None:
        return None
    matches = []
    for event in events:
        when = utc_time(event.get("commence_time"))
        if (when and abs((when - start).total_seconds()) <= 1800
                and _same_team(game.get("home"), event.get("home_team"))
                and _same_team(game.get("away"), event.get("away_team"))):
            matches.append(event)
    if not matches:
        return None
    best_rank = max(_market_source_rank(event) for event in matches)
    best = [event for event in matches if _market_source_rank(event) == best_rank]
    # Ambiguity within the same provider still fails closed for doubleheaders.
    return best[0] if len(best) == 1 else None

def _american_to_prob(x: float) -> float:
    x = float(x)
    return (-x)/((-x)+100) if x < 0 else 100/(x+100)

def _devig(a: float, b: float) -> tuple[float, float]:
    s = a+b
    return (a/s, b/s) if s else (.5, .5)

def _market(event: dict | None) -> dict:
    return parse_game_market(event)

def _score(market: dict) -> dict:
    total, spread = market.get("total"), market.get("home_spread")
    if total is None:
        return {"home": None, "away": None, "method": "unavailable_without_total"}
    margin = -float(spread) if spread is not None else 0.0
    return {"home": round(max(0, (float(total)+margin)/2), 1), "away": round(max(0, (float(total)-margin)/2), 1), "method": "consensus_total_plus_spread"}

def _requested_prop_markets(sport: str, requested: str | None = None) -> list[str]:
    supported = [*PROP_MARKETS[sport], *PROP_ALTERNATE_MARKETS[sport]]
    if not requested:
        return list(PROP_DEFAULT_LIVE_MARKETS[sport])
    wanted = [item.strip() for item in requested.split(",") if item.strip()]
    invalid = [item for item in wanted if item not in supported]
    if invalid:
        raise ValueError(f"unsupported {sport} prop market(s): {', '.join(invalid)}")
    # Preserve caller order while removing duplicates.
    return list(dict.fromkeys(wanted))


def _prop_payload(sport: str, event_id: str, requested: str | None = None) -> dict:
    markets = _requested_prop_markets(sport, requested)
    params = {
        "apiKey": _odds_key(),
        "regions": "us",
        "markets": ",".join(markets),
        "oddsFormat": "american",
        "dateFormat": "iso",
    }
    raw = _timed(
        f"{sport}.props",
        lambda: _json(
            f"https://api.the-odds-api.com/v4/sports/{SPORT_KEYS[sport]}/events/{event_id}/odds",
            params=params,
            timeout=12,
        ),
    )
    if not isinstance(raw, dict) or str(raw.get("id")) != str(event_id):
        raise ProviderError("Provider event response does not match requested event")
    return {
        "sport": sport, "event_id": event_id,
        "configured_markets": PROP_MARKETS[sport],
        "alternate_markets": PROP_ALTERNATE_MARKETS[sport],
        "requested_markets": markets,
        **parse_props(raw, sport, markets),
    }

def _primary_prop_provider_ready() -> bool:
    return bool(os.getenv("ODDS_API_KEY", "").strip()) and (
        os.getenv("CREDENTIAL_ROTATION_CONFIRMED", "").strip().lower() == "true"
    )


def _keyless_prop_payload_for_game(
    sport: str,
    game: dict[str, Any],
    requested: str | None = None,
) -> dict[str, Any]:
    markets = _requested_prop_markets(sport, requested)
    events = _timed(
        f"{sport}.props.public_sportsbook_keyless",
        lambda: keyless_prop_events(sport, markets),
    )
    raw = _match_odds(game, events)
    if raw is None:
        return {
            "sport": sport,
            "event_id": game.get("event_id"),
            "provider": "public keyless sportsbook fallback",
            "configured_markets": PROP_MARKETS[sport],
            "alternate_markets": PROP_ALTERNATE_MARKETS[sport],
            "default_live_markets": PROP_DEFAULT_LIVE_MARKETS[sport],
            "requested_markets": markets,
            "props": [],
            "status": "KEYLESS_SPORTSBOOK_NO_MATCHED_PROP_EVENT",
            "message": (
                "No current keyless sportsbook prop event matched this schedule "
                "event by teams and verified start time."
            ),
        }
    parsed = parse_props(raw, sport, markets)
    return {
        "sport": sport,
        "event_id": game.get("event_id"),
        "provider_event_id": raw.get("id"),
        "provider": str(raw.get("market_source") or "public keyless sportsbook fallback"),
        "credential_required": False,
        "configured_markets": PROP_MARKETS[sport],
        "alternate_markets": PROP_ALTERNATE_MARKETS[sport],
        "default_live_markets": PROP_DEFAULT_LIVE_MARKETS[sport],
        "requested_markets": markets,
        **parsed,
    }


def _props_for_game(
    sport: str,
    game: dict[str, Any],
    matched_odds_event: dict[str, Any] | None = None,
    requested: str | None = None,
) -> dict[str, Any]:
    if _primary_prop_provider_ready() and matched_odds_event is not None:
        provider_event_id = matched_odds_event.get("id")
        if provider_event_id:
            try:
                payload = _prop_payload(sport, str(provider_event_id), requested)
                payload["provider"] = "The Odds API v4"
                payload["credential_required"] = True
                return payload
            except Exception:
                pass

    try:
        return _keyless_prop_payload_for_game(sport, game, requested)
    except ValueError:
        raise
    except Exception as exc:
        return {
            "sport": sport,
            "event_id": game.get("event_id"),
            "provider": "public keyless sportsbook fallback",
            "credential_required": False,
            "configured_markets": PROP_MARKETS[sport],
            "alternate_markets": PROP_ALTERNATE_MARKETS[sport],
            "default_live_markets": PROP_DEFAULT_LIVE_MARKETS[sport],
            "requested_markets": _requested_prop_markets(sport, requested),
            "props": [],
            "status": "KEYLESS_SPORTSBOOK_UNAVAILABLE",
            "message": (
                "The keyless sportsbook fallback did not return a validated prop "
                f"board ({type(exc).__name__}). No prop was fabricated."
            ),
        }


def _matches_search_query(q: str, game: dict[str, Any], sport: str, d: date_cls) -> bool:
    raw = str(q or "").strip()
    if not raw:
        return True
    haystack = _norm(" ".join([
        str(game.get("home") or ""),
        str(game.get("away") or ""),
        str(game.get("matchup") or ""),
        str(sport or ""),
        d.isoformat(),
        d.strftime("%m/%d/%Y"),
    ]))
    whole = _norm(raw)
    tokens = [_norm(token) for token in raw.split() if _norm(token)]
    return bool((whole and whole in haystack) or (tokens and all(token in haystack for token in tokens)))


def _match_live_game(game: dict[str, Any], live_payload: dict[str, Any]) -> dict[str, Any] | None:
    candidates = live_payload.get("games") or []
    event_id = str(game.get("event_id") or "")
    exact = next(
        (
            row
            for row in candidates
            if str(row.get("event_id") or "") == event_id and event_id
        ),
        None,
    )
    if exact is not None:
        return exact
    return next(
        (
            row
            for row in candidates
            if _same_team(game.get("home"), row.get("home"))
            and _same_team(game.get("away"), row.get("away"))
        ),
        None,
    )


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
        live_boards = {
            s: pool.submit(_keyless_live_scoreboard, s, d)
            for s in selected
        }
        forms = {
            s: pool.submit(
                _timed,
                f"{s}.recent_form",
                lambda sport=s: _recent_form_snapshot(sport, d),
            )
            for s in selected
        }
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
                    "error": type(exc).__name__,
                }
            try:
                form_snapshot = forms[s].result()
            except Exception:
                form_snapshot = {"teams": {}}
            try:
                live_payload = live_boards[s].result()
            except Exception:
                live_payload = {
                    "sport": s,
                    "provider": None,
                    "credential_required": False,
                    "games": [],
                }
            for game in sched:
                if not _matches_search_query(q, game, s, d):
                    continue
                live_row = _match_live_game(game, live_payload)
                oe = _match_odds(game, odd_events)
                market = _market(oe)
                market_score = _score(market)
                market_hp = market.get("home_probability")
                form = _recent_form_prediction(s, game, d, form_snapshot)

                hp = market_hp
                score = market_score
                probability_source = (
                    "fresh_de_vigged_consensus_moneyline"
                    if market_hp is not None
                    else "unavailable"
                )
                prediction_reasoning = (
                    "Fresh pregame market baseline is active because no signed trained "
                    "artifact has passed every v8 promotion and runtime-security gate."
                    if market_hp is not None
                    else "Fresh pregame moneyline probability is unavailable."
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

                if form is not None:
                    form_score = form.get("projected_score") or {}
                    if score.get("home") is None and form_score.get("home") is not None:
                        score = form_score
                    if hp is None and form.get("home_win_probability") is not None:
                        hp = float(form["home_win_probability"])
                        probability_source = str(form.get("source") or "keyless_recent_form_heuristic")
                        prediction_reasoning = str(
                            form.get("note")
                            or "A keyless chronological recent-form fallback generated this projection."
                        )

                predictions = _prediction_bundle(
                    game,
                    market,
                    score,
                    hp,
                    probability_source,
                    prediction_reasoning,
                    form,
                )
                item = {
                    **game,
                    "date": d.isoformat(),
                    "event_time_pacific": _event_time_pacific(game.get("event_time")),
                    "timezone": "America/Los_Angeles",
                    "matchup": f"{game.get('away')} @ {game.get('home')}",
                    "odds_event_id": oe.get("id") if oe else None,
                    "live": (
                        {
                            "provider": live_payload.get("provider"),
                            "status": live_row.get("status"),
                            "state": live_row.get("state"),
                            "completed": live_row.get("completed"),
                            "period": live_row.get("period"),
                            "clock": live_row.get("clock"),
                            "home_score": live_row.get("home_score"),
                            "away_score": live_row.get("away_score"),
                        }
                        if live_row is not None
                        else {
                            "provider": live_payload.get("provider"),
                            "status": game.get("status"),
                            "state": None,
                            "completed": None,
                            "period": None,
                            "clock": None,
                            "home_score": None,
                            "away_score": None,
                        }
                    ),
                    "market": market,
                    "projected_score": score,
                    "predictions": predictions,
                    "home_win_probability": hp,
                    "probability_source": probability_source,
                    "prediction_reasoning": prediction_reasoning,
                    "pick": predictions["moneyline"]["pick"],
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
                if include_props:
                    try:
                        prop_payload = _props_for_game(s, game, oe)
                        item["props_to_watch"] = prop_payload.get("props", [])[
                            : max(0, min(int(props_limit), 20))
                        ]
                        item["props_status"] = prop_payload.get("status")
                        item["props_provider"] = prop_payload.get("provider")
                    except Exception as exc:
                        item["props_error"] = type(exc).__name__
                        item["props_status"] = "PROP_LOOKUP_FAILED_CLOSED"
                games.append(item)
    return {"query": q, "date": d.isoformat(), "sports": selected, "fresh_fetch": True, "games": games, "source_telemetry": _SOURCE}

@app.get("/api/v1/data/providers", include_in_schema=False)
@app.get("/v1/data/providers")
def data_providers():
    inventory = json.loads((Path(__file__).parent / "public_api_review.json").read_text())
    inventory["backend_version"] = APP_VERSION
    inventory["runtime"] = {
        "weather_default": "NWS",
        "open_meteo_noncommercial_enabled": os.getenv("OPEN_METEO_ACCESS", "disabled").lower() == "noncommercial",
        "primary_odds_ready": _primary_prop_provider_ready(),
        "context_used_in_prediction": False,
    }
    return inventory


@app.get("/api/v1/context/weather", include_in_schema=False)
@app.get("/v1/context/weather")
def weather(lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180),
            at: str | None = None, provider: str = "nws"):
    try:
        return weather_context(lat, lon, at, provider)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@app.get("/api/v1/context/news/{sport}", include_in_schema=False)
@app.get("/v1/context/news/{sport}")
def news(sport: str, limit: int = Query(5, ge=1, le=20)):
    try:
        return sports_news(sport.upper(), limit)
    except ValueError:
        raise HTTPException(404, "unsupported sport") from None


@app.get("/api/live/sources", include_in_schema=False)
@app.get("/api/v1/live/sources", include_in_schema=False)
@app.get("/v1/live/sources")
def live_sources():
    return {
        "credential_required": False,
        "sports": KEYLESS_LIVE_SOURCES,
        "note": (
            "These keyless feeds replace credentials for schedules, live scores, "
            "game details and play-by-play/boxscore data. They do not replace "
            "sportsbook odds or player-prop feeds."
        ),
    }


@app.get("/api/live/{sport}/scoreboard", include_in_schema=False)
@app.get("/api/v1/live/{sport}/scoreboard", include_in_schema=False)
@app.get("/v1/live/{sport}/scoreboard")
def live_scoreboard(sport: str, date: str | None = None):
    s = sport.upper()
    if s not in SPORTS:
        raise HTTPException(404, "unsupported sport")
    try:
        d = date_cls.fromisoformat(date) if date else _pacific_today()
        return _keyless_live_scoreboard(s, d)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(
            502,
            f"keyless {s} live scoreboard fetch failed: {type(exc).__name__}: {exc}",
        )


@app.get("/api/live/{sport}/game/{event_id}", include_in_schema=False)
@app.get("/api/v1/live/{sport}/game/{event_id}", include_in_schema=False)
@app.get("/v1/live/{sport}/game/{event_id}")
def live_game(sport: str, event_id: str):
    s = sport.upper()
    if s not in SPORTS:
        raise HTTPException(404, "unsupported sport")
    try:
        return _keyless_live_game(s, event_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(
            502,
            f"keyless {s} live game fetch failed: {type(exc).__name__}: {exc}",
        )


@app.get("/")
def root():
    return {
        "service": "PhilthySports Powerhouse",
        "status": "ok",
        "version": APP_VERSION,
        "health": "/health",
        "system_status": "/v1/system/status",
        "models_status": "/v1/models/status",
        "best_three_leg_parlays": "/v1/parlays/best3",
    }

@app.head("/")
def root_head():
    return None

@app.get("/api/health", include_in_schema=False)
@app.get("/v1/health", include_in_schema=False)
@app.get("/health")
def health():
    commit = os.getenv("RENDER_GIT_COMMIT", "")
    return {"status": "ok", "service": "philthysports-runtime", "version": APP_VERSION,
            "deployment_commit": commit if re.fullmatch(r"[a-fA-F0-9]{40}", commit) else None}

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
        "hybrid_fallback_sports": [sport for sport, gate in gates.items() if not gate["passed"]],
        "baseline_fallback_sports": [sport for sport, gate in gates.items() if not gate["passed"]],
    }


@app.get("/api/v1/providers/canary", include_in_schema=False)
@app.get("/v1/providers/canary")
def provider_canary(historical_probe: bool = False):
    return live_provider_canaries(historical_probe=historical_probe)

@app.get("/api/system/status", include_in_schema=False)
@app.get("/api/v1/system/status", include_in_schema=False)
@app.get("/v1/system/status")
def system_status():
    rotation = os.getenv("CREDENTIAL_ROTATION_CONFIRMED", "").strip().lower() == "true"
    provider_key_state = {
        "the_odds_api": bool(os.getenv("ODDS_API_KEY", "").strip()),
        "odds_api_net": bool(os.getenv("ODDS_API_NET_KEY", "").strip()),
        "sportradar": bool(os.getenv("SPORTRADAR_API_KEY", "").strip()),
    }
    odds_key = any(provider_key_state.values())
    credential_status = (
        "CONFIGURED_CANARY_EVIDENCE_REQUIRED" if rotation and odds_key
        else "BLOCKED_ROTATION_CONFIRMATION_REQUIRED" if odds_key
        else "BLOCKED_FRESH_ROTATED_KEY_REQUIRED"
    )
    credential_action = (
        "A server-side key is configured and rotation is confirmed. A successful live provider canary and revocation evidence are still required."
        if rotation and odds_key else
        "A server-side key is configured, but credential rotation has not been confirmed. Verify issuer-side revocation and replacement before enabling it."
        if odds_key else
        "Configure a newly issued server-side odds key after revoking exposed credentials. Keyless feeds remain available."
    )
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
    capture = V8_GATE_STATUS.get("evidence_capture") or {}
    capture_verified = (
        capture.get("verified") is True
        and capture.get("workflow_conclusion") == "success"
        and capture.get("branch") == "evidence-snapshots"
        and bool(capture.get("captured_at_utc"))
        and bool(capture.get("canonical_rows"))
        and bool(capture.get("canonical_sha256"))
    )

    evidence_storage = evidence_storage_status()
    counts = capture.get("canonical_rows") or {}
    policy = V8_GATE_STATUS.get("sample_policy") or {}
    sample_summary = "; ".join(
        f"{sport} {int(counts.get(sport) or 0)}/{int((policy.get(sport) or {}).get("minimum_total_rows") or 0)}"
        for sport in SPORTS
    )

    remaining = [
        "physical Android-device end-to-end smoke testing",
        "rollback drill and alert validation",
    ]
    if not evidence_storage.get("durable"):
        remaining.insert(0, "durable runtime prediction ledger storage")
    remaining.insert(0, "fresh live odds/props provider canary and provider-side revocation evidence")
    if not promotion_pass:
        remaining.insert(0, "four sport trained model promotion evidence")

    return {
        "api_version": APP_VERSION,
        "execution_mode": "MANUAL_REVIEW_ONLY",
        "model_policy": "EVIDENCE_GATED_ENSEMBLE",
        "runtime_behavior": "promoted trained model when its evidence gate passes; otherwise a governed hybrid fallback uses fresh de-vigged market evidence when available and chronological completed-game form when market probability is unavailable",
        "gates": {
            "chronology": "PASS" if chronology_pass else "BLOCKED_EVIDENCE",
            "calibration": "PASS" if calibration_pass else "BLOCKED_EVIDENCE",
            "leakage": "PASS" if leakage_pass else "BLOCKED_EVIDENCE",
            "provenance": "PASS" if provenance_pass else "BLOCKED_EVIDENCE",
            "four_sport_model_promotion": "PASS" if promotion_pass else "BLOCKED_EVIDENCE",
            "credential_core_keyless": "PASS",
            "credential_live_odds_props": credential_status,
            "stable_android_signing": "PASS_CI_PINNED_CERTIFICATE",
            "immutable_pregame_evidence_capture": (
                "PASS_VERIFIED_CHECKSUMMED_HISTORY"
                if capture_verified
                else "CONFIGURED_LAST_RUN_VERIFICATION_REQUIRED"
            ),
        },
        "gate_display": {
            "chronology": "Passed" if chronology_pass else (
                "Capture verified · promotion pending" if capture_verified else "Evidence needed"
            ),
            "calibration": "Passed" if calibration_pass else "Control implemented · promotion pending",
            "leakage": "Passed" if leakage_pass else "Control implemented · promotion pending",
            "provenance": "Passed" if provenance_pass else (
                "Dataset hashes verified · model provenance pending" if capture_verified else "Evidence needed"
            ),
            "four_sport_model_promotion": "Passed" if promotion_pass else "Sample threshold pending",
            "credential_core_keyless": "Passed",
            "credential_live_odds_props": (
                "Canary pending" if rotation and odds_key else
                "Rotation confirmation pending" if odds_key else
                "Fresh credential pending"
            ),
            "stable_android_signing": "Passed",
            "immutable_pregame_evidence_capture": "Passed" if capture_verified else "Verification needed",
        },
        "gate_details": {
            "chronology": (
                "Canonical pregame capture is checksum-verified under as_of < event_time. "
                "Per-sport promoted-model chronology remains part of the strict promotion gate."
            ),
            "calibration": (
                "Chronological OOF-only calibration and ECE/log-loss/Brier gates are implemented. "
                "No sport has enough canonical settled rows yet to produce a promoted calibration artifact."
            ),
            "leakage": (
                "Temporal leakage checks are implemented fail-closed. A promoted sport artifact still requires "
                "its own successful leakage evidence."
            ),
            "provenance": (
                "Canonical dataset and source-manifest hashes are verified. Signed promoted-model artifact "
                "provenance remains pending until a sport passes promotion."
            ),
            "credential_live_odds_props": credential_action,
            "four_sport_model_promotion": (
                "All four trained models passed their promotion checks." if promotion_pass else
                f"Current canonical settled rows versus strict minimums: {sample_summary}. "
                "Fresh governed market baselines remain active until each sport passes."
            ),
        },
        "evidence_storage": evidence_storage,
        "evidence_capture_gate": {
            **capture,
            "verified_by_runtime_manifest": capture_verified,
        },
        "credential_gate": {
            "core_runtime_requires_secret": False,
            "rotation_confirmed": rotation,
            "odds_api_key_configured": provider_key_state["the_odds_api"],
            "odds_api_net_key_configured": provider_key_state["odds_api_net"],
            "sportradar_api_key_configured": provider_key_state["sportradar"],
            "any_credentialed_provider_configured": odds_key,
            "odds_props_live_allowed": rotation and odds_key,
            "provider_revocation_independently_verified": False,
            "live_canary_evidence_verified": False,
        },
        "production_ready": False,
        "production_ready_reason": (
            "The backend has HTTPS, pinned Android signing, four-sport adapters, and a verified checksummed pregame evidence history. "
            "Production-ready remains blocked until four sport-specific trained models accumulate sufficient resolved samples and pass every v8 promotion gate, "
            "live provider canaries and credential revocation are evidenced, rollback/alert validation is recorded, and a physical-device end-to-end smoke run is recorded."
            + (" Durable runtime ledger storage is active." if evidence_storage.get("durable") else " Durable runtime ledger storage is not active yet.")
        ),
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

@app.get("/api/models/registry", include_in_schema=False)
@app.get("/api/v1/models/registry", include_in_schema=False)
@app.get("/v1/models/registry")
def model_registry():
    gates = _all_model_gates()
    return {
        "registry_version": CANDIDATE_REGISTRY.get("registry_version", 1),
        "policy": CANDIDATE_REGISTRY.get("policy"),
        "promoted_sports": [sport for sport, gate in gates.items() if gate["passed"]],
        "sports": {
            sport: {
                **((CANDIDATE_REGISTRY.get("sports") or {}).get(sport) or {}),
                "promotion_state": (
                    "PROMOTED_TRAINED_MODEL"
                    if gates[sport]["passed"]
                    else ((CANDIDATE_REGISTRY.get("sports") or {}).get(sport) or {}).get(
                        "promotion_state", "NO_PROMOTED_MATCHUP_MODEL"
                    )
                ),
                "promoted_artifact_loaded": PROMOTED_MODELS.get(sport) is not None,
                "promotion_gate_passed": gates[sport]["passed"],
                "runtime_mode": _runtime_mode_for(sport),
                "active_model_id": (
                    PROMOTED_MODELS[sport].get("model_id")
                    if PROMOTED_MODELS.get(sport) is not None and gates[sport]["passed"]
                    else MODEL_REGISTRY[sport].get("model_id")
                ),
            }
            for sport in SPORTS
        },
    }


@app.get("/api/training/reconstruction", include_in_schema=False)
@app.get("/api/v1/training/reconstruction", include_in_schema=False)
@app.get("/v1/training/reconstruction")
def training_reconstruction():
    return {
        **DRIVE_RECONSTRUCTION,
        "additional_evidence": DRIVE_RECONSTRUCTION_ADDENDUM,
    }

@app.get("/api/system/props", include_in_schema=False)
@app.get("/api/v1/system/props", include_in_schema=False)
@app.get("/v1/system/props")
def prop_capabilities():
    configured = bool(os.getenv("ODDS_API_KEY", "").strip())
    rotated = os.getenv("CREDENTIAL_ROTATION_CONFIRMED", "").strip().lower() == "true"
    enabled = configured and rotated
    keyless = keyless_sportsbook_status()
    return {
        "primary_provider": "The Odds API v4",
        "credential_configured": configured,
        "credential_rotation_confirmed": rotated,
        "primary_live_player_props_enabled": enabled,
        "keyless_fallback": keyless,
        "keyless_fallback_configured": True,
        "status": (
            "PRIMARY_CONFIGURED_WITH_KEYLESS_FALLBACK"
            if enabled
            else "KEYLESS_FALLBACK_CONFIGURED_PRIMARY_KEY_NOT_REQUIRED"
        ),
        "sports": {
            s: {
                "supported": True,
                "markets": PROP_MARKETS[s],
                "alternate_markets": PROP_ALTERNATE_MARKETS[s],
                "default_live_markets": PROP_DEFAULT_LIVE_MARKETS[s],
            }
            for s in SPORTS
        },
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

def _next_scheduled_games(
    sport: str,
    start: date_cls,
    *,
    max_days: int = 14,
    limit: int = 3,
) -> list[dict[str, Any]]:
    for offset in range(1, max_days + 1):
        d = start + timedelta(days=offset)
        try:
            scheduled = _schedule(sport, d)
        except Exception:
            continue
        if not scheduled:
            continue
        try:
            payload = _search(
                sport=sport,
                date=d.isoformat(),
                include_props=False,
                props_limit=0,
            )
            rows = list(payload.get("games") or [])
        except Exception:
            rows = []
        if rows:
            return rows[: max(1, limit)]
    return []


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
    today_sports = {str(game.get("sport") or "").upper() for game in games}
    missing = [sport for sport in SPORTS if sport not in today_sports]
    next_games_by_sport: dict[str, list[dict[str, Any]]] = {}
    if missing:
        with ThreadPoolExecutor(max_workers=len(missing)) as pool:
            futures = {
                sport: pool.submit(_next_scheduled_games, sport, start)
                for sport in missing
            }
            for sport, future in futures.items():
                try:
                    next_games_by_sport[sport] = future.result()
                except Exception:
                    next_games_by_sport[sport] = []

    return {
        "query": "",
        "date": start.isoformat(),
        "dates": dates,
        "timezone": "America/Los_Angeles",
        "sports": list(SPORTS),
        "fresh_fetch": True,
        "games": games,
        "next_games_by_sport": next_games_by_sport,
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
    s = sport.upper()
    if s not in SPORTS:
        raise HTTPException(404, "unsupported sport")

    search_dates: list[str] = []
    if date:
        try:
            search_dates = [date_cls.fromisoformat(date).isoformat()]
        except ValueError:
            raise HTTPException(400, "date must be YYYY-MM-DD") from None
    else:
        start = _pacific_today()
        search_dates = [
            (start + timedelta(days=offset)).isoformat()
            for offset in (0, 1, 2, 3, 4, 5, 6, 7, -1)
        ]

    game = None
    resolved_date = None
    for candidate_date in search_dates:
        try:
            result = _search(sport=s, date=candidate_date)
        except Exception:
            continue
        game = next(
            (
                g
                for g in result["games"]
                if str(g["event_id"]) == str(event_id)
            ),
            None,
        )
        if game is not None:
            resolved_date = candidate_date
            break

    if not game:
        raise HTTPException(
            404,
            "game not found in the requested or nearby fresh schedule dates",
        )
    if resolved_date and not game.get("date"):
        game["date"] = resolved_date
    score, market = game["projected_score"], game["market"]
    predictions = game.get("predictions") or {}
    moneyline_prediction = predictions.get("moneyline") or {}
    spread_prediction = predictions.get("spread") or {}
    total_prediction = predictions.get("total") or {}
    fallback = predictions.get("fallback") or {}

    reasons: list[str] = []
    if market.get("home_probability") is not None:
        reasons.append(
            f"Fresh de-vigged consensus moneyline implies home win probability "
            f"{float(market['home_probability']):.1%}."
        )
    elif moneyline_prediction.get("home_win_probability") is not None:
        source = str(moneyline_prediction.get("source") or "keyless fallback")
        reasons.append(
            f"Sportsbook moneyline probability is unavailable, so PhilthySports generated "
            f"a {float(moneyline_prediction['home_win_probability']):.1%} home-side estimate "
            f"from {source.replace('_', ' ')}."
        )
    else:
        reasons.append("No usable pregame moneyline or chronological team-form estimate is available.")

    if spread_prediction.get("pick") is not None:
        if spread_prediction.get("probability") is not None:
            reasons.append(
                f"Spread lean: {spread_prediction['pick']} "
                f"{float(spread_prediction['line']):+g} at "
                f"{float(spread_prediction['probability']):.1%} after de-vigging."
            )
        else:
            reasons.append(
                f"Spread lean: {spread_prediction['pick']} "
                f"{float(spread_prediction['line']):+g}, generated by comparing the "
                "chronological recent-form score projection with the current market line."
            )
    else:
        reasons.append("No usable spread line is available, so no against-the-spread side is fabricated.")

    if total_prediction.get("pick") is not None:
        if total_prediction.get("probability") is not None:
            reasons.append(
                f"Total lean: {total_prediction['pick']} "
                f"{float(total_prediction['line']):g} at "
                f"{float(total_prediction['probability']):.1%} after de-vigging."
            )
        else:
            reasons.append(
                f"Total lean: {total_prediction['pick']} {float(total_prediction['line']):g}; "
                f"recent-form projected total is {float(total_prediction.get('projected_total') or 0):g}."
            )
    elif total_prediction.get("projected_total") is not None:
        reasons.append(
            f"Projected game total is {float(total_prediction['projected_total']):g}; "
            "no sportsbook total line is available for an over/under comparison."
        )
    else:
        reasons.append("No score-form data is available for a total projection.")

    if score.get("home") is not None and score.get("away") is not None:
        reasons.append(
            f"Projected score uses {str(score.get('method') or 'available pregame inputs').replace('_', ' ')}."
        )
    if fallback:
        reasons.append(
            str(fallback.get("note") or "Fallback input uses completed games before the matchup date only.")
        )
    reasons.append(game.get("prediction_reasoning") or "No governed probability explanation is available.")

    weather_info = game_weather_context(game)
    game["weather_context"] = weather_info
    if weather_info.get("available"):
        reasons.append(
            f"Venue forecast from {weather_info['provider']}: "
            f"{weather_info['temperature_c']:g} °C at game time. "
            "Weather is context only and has not changed this prediction."
        )

    game["score_prediction"] = {
        "home": score.get("home"),
        "away": score.get("away"),
        "pick": moneyline_prediction.get("pick") or game.get("pick"),
        "reasons": reasons,
    }
    # Keep the legacy key so existing APKs immediately benefit from the backend fix.
    game["market_predictions"] = {
        "moneyline": {
            **moneyline_prediction,
            "probability_source": moneyline_prediction.get("source"),
        },
        "spread": spread_prediction,
        "total": total_prediction,
    }
    game["prediction_status"] = (
        "GENERATED"
        if bool(predictions.get("generated"))
        else "INSUFFICIENT_PREGAME_EVIDENCE"
    )
    game["team_totals"] = {
        "home": score.get("home"),
        "away": score.get("away"),
        "method": score.get("method"),
    }
    return game

@app.get("/api/games/{sport}/{event_id}/props", include_in_schema=False)
@app.get("/api/v1/games/{sport}/{event_id}/props", include_in_schema=False)
@app.get("/v1/games/{sport}/{event_id}/props")
def props(
    sport: str,
    event_id: str,
    odds_event_id: str | None = None,
    markets: str | None = None,
    date: str | None = None,
):
    s = sport.upper()
    if s not in SPORTS:
        raise HTTPException(400, "unsupported sport")
    try:
        game = game_detail(s, event_id, date)
        game_date = date_cls.fromisoformat(str(game.get("date") or _pacific_today()))
        matched = None
        try:
            matched = _match_odds(game, _odds(s, game_date))
        except Exception:
            matched = None
        # Preserve an explicitly mapped primary-provider event id when supplied.
        if (
            matched is None
            and odds_event_id
            and _primary_prop_provider_ready()
        ):
            matched = {
                "id": odds_event_id,
                "market_source": "THE_ODDS_API_V4",
                "home_team": game.get("home"),
                "away_team": game.get("away"),
                "commence_time": game.get("event_time"),
            }
        return _props_for_game(s, game, matched, markets)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            502,
            (
                "Player-prop providers are unavailable after primary and keyless "
                f"fallback checks ({type(exc).__name__})."
            ),
        ) from None

@app.get("/api/games/{sport}/{event_id}/parlays", include_in_schema=False)
@app.get("/api/v1/games/{sport}/{event_id}/parlays", include_in_schema=False)
@app.get("/v1/games/{sport}/{event_id}/parlays")
def parlays(sport: str, event_id: str, date: str | None = None):
    s = sport.upper()
    game = game_detail(s, event_id, date)
    matched = None
    try:
        game_date = date_cls.fromisoformat(str(game.get("date") or _pacific_today()))
        matched = _match_odds(game, _odds(s, game_date))
    except Exception:
        matched = None
    try:
        props_payload = _props_for_game(s, game, matched)
    except Exception:
        props_payload = {"props": [], "status": "PROP_LOOKUP_FAILED_CLOSED"}
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


# ---------------------------------------------------------------------------
# Best-picks boards used by the PhilthyParleys mobile dashboard.
#
# These endpoints intentionally fail closed. A missing sportsbook price,
# timestamp, roster match, or recommended prop side is rendered as unavailable;
# it is never replaced with a synthetic selection.
# ---------------------------------------------------------------------------

_ROSTER_CACHE: dict[tuple[str, str], tuple[float, set[str]]] = {}
_ROSTER_TTL_SECONDS = 900
_BEST_BOARD_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_BEST_BOARD_TTL_SECONDS = 60


def _future_pregame(game: dict[str, Any]) -> bool:
    event_time = utc_time(game.get("event_time"))
    return bool(event_time and event_time > datetime.now(timezone.utc))


def _game_market_candidates(game: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only fresh, sportsbook-backed ML/spread/total selections."""
    if not _future_pregame(game):
        return []

    market = game.get("market") or {}
    sport = str(game.get("sport") or "").upper()
    event_id = str(game.get("event_id") or "")
    event_time = game.get("event_time")
    matchup = game.get("matchup") or f"{game.get('away')} @ {game.get('home')}"
    base = {
        "available": True,
        "sport": sport,
        "event_id": event_id,
        "event_time": event_time,
        "event_time_pacific": game.get("event_time_pacific"),
        "date": game.get("date"),
        "matchup": matchup,
        "category": "GAME_PROP",
        "model_state": game.get("model_status"),
        "evidence_basis": "FRESH_TWO_SIDED_SPORTSBOOK_DEVIG",
    }
    candidates: list[dict[str, Any]] = []

    ml_pick = market.get("moneyline_pick") or game.get("pick")
    ml_probability = market.get("moneyline_pick_probability")
    if ml_probability is None:
        hp = market.get("home_probability")
        ap = market.get("away_probability")
        if hp is not None and ap is not None:
            if float(hp) >= float(ap):
                ml_pick, ml_probability = game.get("home"), float(hp)
            else:
                ml_pick, ml_probability = game.get("away"), float(ap)
    if (
        ml_pick
        and ml_probability is not None
        and market.get("moneyline_best_book")
        and market.get("moneyline_best_price") is not None
        and market.get("moneyline_last_update")
    ):
        candidates.append({
            **base,
            "type": "moneyline",
            "market_label": "MONEYLINE",
            "label": f"{ml_pick} ML",
            "selection": ml_pick,
            "line": None,
            "probability": round(float(ml_probability), 6),
            "best_available_book": market.get("moneyline_best_book"),
            "best_available_price": market.get("moneyline_best_price"),
            "as_of": market.get("moneyline_last_update"),
            "reason": (
                f"{ml_pick} is the stronger fresh moneyline side at "
                f"{float(ml_probability):.1%} after removing the paired-book vig. "
                f"The displayed price is the best verified contributing quote from "
                f"{market.get('moneyline_best_book')} at the recorded quote time. "
                "No unverified model edge is added."
            ),
        })

    spread_pick = market.get("spread_pick")
    spread_probability = market.get("spread_pick_probability")
    if spread_pick and spread_probability is not None:
        spread_line = (
            market.get("home_spread")
            if spread_pick == game.get("home")
            else market.get("away_spread")
        )
        if (
            spread_line is not None
            and market.get("spread_best_book")
            and market.get("spread_best_price") is not None
            and market.get("spread_last_update")
        ):
            candidates.append({
                **base,
                "type": "spread",
                "market_label": "POINT SPREAD",
                "label": f"{spread_pick} {float(spread_line):+g}",
                "selection": spread_pick,
                "line": float(spread_line),
                "probability": round(float(spread_probability), 6),
                "best_available_book": market.get("spread_best_book"),
                "best_available_price": market.get("spread_best_price"),
                "as_of": market.get("spread_last_update"),
                "reason": (
                    f"The offered spread {spread_pick} {float(spread_line):+g} "
                    f"has the stronger fresh two-sided de-vigged price at "
                    f"{float(spread_probability):.1%}. The line itself is preserved "
                    f"from {market.get('spread_best_book')}; it is not an averaged or "
                    "fabricated number."
                ),
            })

    total_pick = market.get("total_pick")
    total_probability = market.get("total_pick_probability")
    total_line = market.get("total")
    if (
        total_pick
        and total_probability is not None
        and total_line is not None
        and market.get("total_best_book")
        and market.get("total_best_price") is not None
        and market.get("total_last_update")
    ):
        candidates.append({
            **base,
            "type": "total",
            "market_label": "OVER / UNDER",
            "label": f"{total_pick} {float(total_line):g}",
            "selection": total_pick,
            "line": float(total_line),
            "probability": round(float(total_probability), 6),
            "best_available_book": market.get("total_best_book"),
            "best_available_price": market.get("total_best_price"),
            "as_of": market.get("total_last_update"),
            "reason": (
                f"{total_pick} {float(total_line):g} is the stronger side of the "
                f"current two-sided total at {float(total_probability):.1%} after "
                f"de-vigging. The quoted total and price come from "
                f"{market.get('total_best_book')} and must remain fresh to display."
            ),
        })

    return candidates


def _prop_candidate(
    game: dict[str, Any],
    prop: dict[str, Any],
    *,
    team: str | None = None,
    team_side: str | None = None,
    roster_source: str | None = None,
) -> dict[str, Any] | None:
    side = prop.get("recommended_side")
    probability = prop.get("market_probability")
    line = prop.get("line")
    player = str(prop.get("player") or "").strip()
    book = prop.get("best_available_book")
    price = prop.get("best_available_price")
    as_of = prop.get("best_price_last_update") or prop.get("last_update")
    if (
        not side
        or probability is None
        or line is None
        or not player
        or not book
        or price is None
        or not as_of
    ):
        return None

    return {
        "available": True,
        "sport": str(game.get("sport") or "").upper(),
        "event_id": str(game.get("event_id") or ""),
        "event_time": game.get("event_time"),
        "event_time_pacific": game.get("event_time_pacific"),
        "date": game.get("date"),
        "matchup": game.get("matchup")
        or f"{game.get('away')} @ {game.get('home')}",
        "category": "PLAYER_PROP",
        "type": "player_prop",
        "market_label": str(prop.get("market") or "").replace("_", " ").upper(),
        "label": f"{player} {side} {float(line):g} {prop.get('market')}",
        "player": player,
        "team": team,
        "team_side": team_side,
        "line": float(line),
        "selection": side,
        "probability": round(float(probability), 6),
        "probability_method": prop.get("probability_method"),
        "best_available_book": book,
        "best_available_price": price,
        "as_of": as_of,
        "contributing_books": prop.get("contributing_books") or [],
        "model_state": prop.get("model_state"),
        "roster_verification_source": roster_source,
        "evidence_basis": "FRESH_PLAYER_PROP_TWO_SIDED_DEVIG",
        "reason": (
            f"{player} {side} {float(line):g} is the recommended side because "
            f"fresh complementary prices de-vig to {float(probability):.1%}. "
            f"The best displayed contributing price is {price:+g} at {book}. "
            + (
                f"Player-to-team assignment is verified through {roster_source}. "
                if roster_source
                else ""
            )
            + "This is market evidence, not an invented player projection."
        ),
    }


def _available_props_for_game(
    game: dict[str, Any],
    matched_odds_event: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        payload = _props_for_game(
            str(game.get("sport") or "").upper(),
            game,
            matched_odds_event,
        )
    except Exception as exc:
        return [], {
            "status": "PROP_LOOKUP_FAILED_CLOSED",
            "provider": None,
            "message": f"Fresh prop lookup failed closed ({type(exc).__name__}).",
        }

    candidates = []
    for prop in payload.get("props") or []:
        candidate = _prop_candidate(game, prop)
        if candidate is not None:
            candidates.append(candidate)
    candidates.sort(
        key=lambda row: (
            float(row.get("probability") or 0.0),
            len(row.get("contributing_books") or []),
        ),
        reverse=True,
    )
    return candidates, payload


def _board_for_date(d: date_cls) -> dict[str, Any]:
    key = d.isoformat()
    cached = _BEST_BOARD_CACHE.get(key)
    now = time.time()
    if cached and now - cached[0] <= _BEST_BOARD_TTL_SECONDS:
        return cached[1]

    # The ranked board needs schedules + sportsbook evidence, not the heavier
    # injury/live/recent-form bundle used by the matchup screen. Fetch these two
    # sources per league in parallel so the board stays inside the mobile timeout.
    schedules: dict[str, list[dict[str, Any]]] = {}
    odds: dict[str, list[dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        schedule_jobs = {
            sport: pool.submit(_schedule, sport, d)
            for sport in SPORTS
        }
        odds_jobs = {
            sport: pool.submit(_odds, sport, d)
            for sport in SPORTS
        }
        for sport in SPORTS:
            try:
                schedules[sport] = schedule_jobs[sport].result()
            except Exception:
                schedules[sport] = []
            try:
                odds[sport] = odds_jobs[sport].result()
            except Exception:
                odds[sport] = []

    games: list[dict[str, Any]] = []
    game_candidates: list[dict[str, Any]] = []
    prop_candidates: list[dict[str, Any]] = []
    for sport in SPORTS:
        for scheduled in schedules[sport]:
            game = {
                **scheduled,
                "date": key,
                "event_time_pacific": _event_time_pacific(scheduled.get("event_time")),
                "matchup": f"{scheduled.get('away')} @ {scheduled.get('home')}",
                "market": _market(_match_odds(scheduled, odds[sport])),
                "model_status": _runtime_mode_for(sport),
            }
            if not _future_pregame(game):
                continue
            games.append(game)
            game_candidates.extend(_game_market_candidates(game))

    def pull_sport_props(sport: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        # Keep same-sport lookups sequential. The keyless adapter caches a league
        # board after the first request, preventing a burst of duplicate upstream
        # calls while still scanning every scheduled game.
        for game in (g for g in games if g.get("sport") == sport):
            found, _ = _available_props_for_game(game)
            rows.extend(found)
        return rows

    if games:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                sport: pool.submit(pull_sport_props, sport)
                for sport in SPORTS
                if any(g.get("sport") == sport for g in games)
            }
            for future in futures.values():
                try:
                    prop_candidates.extend(future.result())
                except Exception:
                    continue

    game_candidates.sort(
        key=lambda row: float(row.get("probability") or 0.0),
        reverse=True,
    )
    prop_candidates.sort(
        key=lambda row: float(row.get("probability") or 0.0),
        reverse=True,
    )
    payload = {
        "date": key,
        "timezone": "America/Los_Angeles",
        "games_scanned": len(games),
        "game_candidates": game_candidates,
        "prop_candidates": prop_candidates,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    _BEST_BOARD_CACHE[key] = (now, payload)
    return payload

def _unavailable_pick(
    sport: str,
    category: str,
    label: str,
    reason: str,
    *,
    matchup: str | None = None,
) -> dict[str, Any]:
    return {
        "available": False,
        "sport": sport,
        "category": category,
        "market_label": label,
        "label": "UNAVAILABLE — VERIFIED EVIDENCE REQUIRED",
        "matchup": matchup,
        "probability": None,
        "best_available_book": None,
        "best_available_price": None,
        "as_of": None,
        "reason": reason,
    }


def _best12(date: str | None = None) -> dict[str, Any]:
    d = date_cls.fromisoformat(date) if date else _pacific_today()
    board = _board_for_date(d)
    games = board["game_candidates"]
    props = board["prop_candidates"]
    selections: list[dict[str, Any]] = []
    used: set[tuple[str, str, str]] = set()

    def ident(row: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(row.get("sport") or ""),
            str(row.get("event_id") or ""),
            str(row.get("label") or ""),
        )

    # 4/12: one strongest verified game-market selection from each sport.
    for sport in SPORTS:
        row = next((x for x in games if x.get("sport") == sport), None)
        if row:
            row = {**row, "board_bucket": "GAME_PROP"}
            selections.append(row)
            used.add(ident(row))
        else:
            selections.append(_unavailable_pick(
                sport,
                "GAME_PROP",
                "BEST GAME PROP",
                "No fresh two-sided ML/spread/total quote passed the evidence checks for this sport.",
            ))

    # 4/12: one strongest verified player prop from each sport.
    for sport in SPORTS:
        row = next((x for x in props if x.get("sport") == sport), None)
        if row:
            row = {**row, "board_bucket": "PLAYER_PROP"}
            selections.append(row)
            used.add(ident(row))
        else:
            selections.append(_unavailable_pick(
                sport,
                "PLAYER_PROP",
                "BEST PLAYER PROP",
                "No fresh, paired and de-vigged player-prop recommendation passed the evidence checks for this sport.",
            ))

    # 4/12: one additional best evidence-backed selection per sport. Together this
    # final bucket is the multisport mix and may contain either a game or player prop.
    all_rows = sorted(
        [*games, *props],
        key=lambda row: float(row.get("probability") or 0.0),
        reverse=True,
    )
    for sport in SPORTS:
        row = next(
            (
                x
                for x in all_rows
                if x.get("sport") == sport and ident(x) not in used
            ),
            None,
        )
        if row:
            row = {
                **row,
                "board_bucket": "MULTISPORT_MIX",
                "category": (
                    "MULTISPORT_PLAYER_PROP"
                    if row.get("type") == "player_prop"
                    else "MULTISPORT_GAME_PROP"
                ),
            }
            selections.append(row)
            used.add(ident(row))
        else:
            selections.append(_unavailable_pick(
                sport,
                "MULTISPORT_MIX",
                "BEST MULTISPORT MIX",
                "A second independent fresh selection was not available for this sport; no substitute was fabricated.",
            ))

    available_count = sum(1 for row in selections if row.get("available"))
    return {
        "date": d.isoformat(),
        "timezone": "America/Los_Angeles",
        "requested_picks": 12,
        "available_picks": available_count,
        "breakdown": {
            "game_props": 4,
            "player_props": 4,
            "multisport_mix": 4,
        },
        "picks": selections,
        "status": "OK" if available_count == 12 else "PARTIAL_VERIFIED_COVERAGE",
        "reasoning": [
            "The first four slots are one strongest fresh game-market selection for each of NFL, NBA, MLB and NHL.",
            "The next four slots are one strongest fresh player-prop selection for each sport, using paired prices and de-vigged probability only.",
            "The final four slots form the multisport mix: one additional evidence-backed game or player prop from each sport, so the bucket spans all four leagues.",
            "Every displayed selection must carry a real bookmaker, price and recent quote timestamp. Missing evidence stays visibly unavailable instead of being guessed.",
        ],
    }


def _best_three_leg_parlays(date: str | None = None) -> dict[str, Any]:
    d = date_cls.fromisoformat(date) if date else _pacific_today()
    board = _board_for_date(d)
    all_rows = sorted(
        [*board["game_candidates"], *board["prop_candidates"]],
        key=lambda row: float(row.get("probability") or 0.0),
        reverse=True,
    )
    cards: list[dict[str, Any]] = []

    for sport in SPORTS:
        pool = [row for row in all_rows if row.get("sport") == sport]
        game_pool = [row for row in pool if row.get("type") != "player_prop"]
        prop_pool = [row for row in pool if row.get("type") == "player_prop"]
        used_sets: set[tuple[str, ...]] = set()

        for rank in (1, 2):
            selected: list[dict[str, Any]] = []
            start_offset = rank - 1

            # Force a balanced evidence mix when the sport has both types.
            if game_pool:
                selected.append(game_pool[min(start_offset, len(game_pool) - 1)])
            prop_choice = next(
                (
                    row
                    for row in prop_pool[start_offset:]
                    if row.get("label") not in {x.get("label") for x in selected}
                ),
                None,
            )
            if prop_choice:
                selected.append(prop_choice)

            for row in pool[start_offset:] + pool[:start_offset]:
                if len(selected) >= 3:
                    break
                if any(
                    row.get("event_id") == x.get("event_id")
                    and row.get("label") == x.get("label")
                    for x in selected
                ):
                    continue
                if (
                    sum(1 for x in selected if x.get("event_id") == row.get("event_id"))
                    >= 2
                ):
                    continue
                selected.append(row)

            signature = tuple(sorted(str(x.get("label")) for x in selected))
            if (
                len(selected) != 3
                or len(signature) != 3
                or signature in used_sets
            ):
                cards.append({
                    "sport": sport,
                    "rank": rank,
                    "title": f"{sport} BEST {rank} — 3 LEG",
                    "status": "INSUFFICIENT_VERIFIED_LEGS",
                    "legs": [],
                    "estimated_joint_probability": None,
                    "dependency_method": "UNSCORED_WITHOUT_VALIDATED_DEPENDENCY_MODEL",
                    "reasoning": [
                        "Three distinct fresh sportsbook-backed legs were not simultaneously available.",
                        "PhilthyParleys does not fill missing legs with stale, synthetic or unverified selections.",
                    ],
                })
                continue

            used_sets.add(signature)
            cards.append({
                "sport": sport,
                "rank": rank,
                "title": f"{sport} BEST {rank} — 3 LEG",
                "status": "OK",
                "legs": selected,
                "estimated_joint_probability": None,
                "dependency_method": "UNSCORED_WITHOUT_VALIDATED_DEPENDENCY_MODEL",
                "reasoning": [
                    (
                        "This three-leg card is built only from fresh verified "
                        f"{sport} game markets and player props, ranked by the "
                        "de-vigged probability attached to the offered prices."
                    ),
                    (
                        "The builder prefers a mix of game-market and player-prop "
                        "evidence and limits repeated legs from one event to reduce "
                        "obvious same-game concentration."
                    ),
                    (
                        "Each leg shows its own bookmaker, price, timestamp and "
                        "selection reasoning so the evidence can be reviewed before use."
                    ),
                    (
                        "No joint hit rate is shown because cross-leg dependence has "
                        "not passed the governed validation gate. Manual review remains required."
                    ),
                ],
            })

    return {
        "date": d.isoformat(),
        "timezone": "America/Los_Angeles",
        "parlays_per_sport": 2,
        "legs_per_parlay": 3,
        "sports": list(SPORTS),
        "cards": cards,
        "status": (
            "OK"
            if cards and all(card.get("status") == "OK" for card in cards)
            else "PARTIAL_VERIFIED_COVERAGE"
        ),
    }


def _espn_roster_names(sport: str, team_name: str) -> set[str]:
    cache_key = (sport, _norm(team_name))
    now = time.time()
    cached = _ROSTER_CACHE.get(cache_key)
    if cached and now - cached[0] <= _ROSTER_TTL_SECONDS:
        return cached[1]

    a, b = ESPN[sport]
    directory = _cached_json(
        f"roster-directory:{sport}",
        f"https://site.api.espn.com/apis/site/v2/sports/{a}/{b}/teams",
        params={"limit": 1000},
        ttl_seconds=_ROSTER_TTL_SECONDS,
    )
    entries: list[dict[str, Any]] = []
    for sport_row in directory.get("sports") or []:
        for league in sport_row.get("leagues") or []:
            for wrapper in league.get("teams") or []:
                team = wrapper.get("team") if isinstance(wrapper, dict) else None
                if isinstance(team, dict):
                    entries.append(team)

    wanted = _norm(team_name)

    def aliases(team: dict[str, Any]) -> set[str]:
        values = [
            team.get("displayName"),
            team.get("shortDisplayName"),
            team.get("name"),
            team.get("location"),
            team.get("abbreviation"),
            team.get("nickname"),
        ]
        return {_norm(value) for value in values if value}

    team = next((row for row in entries if wanted in aliases(row)), None)
    if team is None:
        matches = [
            row
            for row in entries
            if any(
                wanted and alias and (wanted in alias or alias in wanted)
                for alias in aliases(row)
            )
        ]
        if len(matches) == 1:
            team = matches[0]
    if team is None:
        _ROSTER_CACHE[cache_key] = (now, set())
        return set()

    team_id = team.get("id") or team.get("uid") or team.get("abbreviation")
    if not team_id:
        _ROSTER_CACHE[cache_key] = (now, set())
        return set()

    roster = _cached_json(
        f"roster:{sport}:{team_id}",
        f"https://site.api.espn.com/apis/site/v2/sports/{a}/{b}/teams/{team_id}/roster",
        ttl_seconds=_ROSTER_TTL_SECONDS,
    )

    names: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            full = value.get("fullName") or value.get("displayName")
            if full and (
                value.get("id") is not None
                or value.get("position") is not None
                or value.get("jersey") is not None
            ):
                normalized = _norm(str(full))
                if normalized:
                    names.add(normalized)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(roster.get("athletes") or [])
    _ROSTER_CACHE[cache_key] = (now, names)
    return names


def _roster_side_for_player(
    sport: str,
    player: str,
    home: str,
    away: str,
) -> tuple[str | None, str | None, str | None]:
    player_norm = _norm(player)
    if not player_norm:
        return None, None, None
    home_names = _espn_roster_names(sport, home)
    away_names = _espn_roster_names(sport, away)

    in_home = player_norm in home_names
    in_away = player_norm in away_names
    if in_home ^ in_away:
        return (
            (home, "HOME", "ESPN roster") if in_home
            else (away, "AWAY", "ESPN roster")
        )

    # Conservative unique initial+surname fallback for provider abbreviations.
    parts = str(player).strip().lower().replace(".", "").split()
    if len(parts) >= 2:
        surname = _norm(parts[-1])
        initial = _norm(parts[0])[:1]

        def loose(roster: set[str]) -> list[str]:
            return [
                name
                for name in roster
                if name.endswith(surname)
                and (not initial or name.startswith(initial))
            ]

        hm, am = loose(home_names), loose(away_names)
        if len(hm) == 1 and not am:
            return home, "HOME", "ESPN roster unique initial/surname match"
        if len(am) == 1 and not hm:
            return away, "AWAY", "ESPN roster unique initial/surname match"

    return None, None, None


def _best9_for_game(
    sport: str,
    event_id: str,
    date: str | None = None,
) -> dict[str, Any]:
    s = sport.upper()
    if s not in SPORTS:
        raise ValueError(f"unsupported sport: {s}")
    game = game_detail(s, event_id, date)
    if not _future_pregame(game):
        return {
            "sport": s,
            "event_id": event_id,
            "matchup": game.get("matchup"),
            "requested_picks": 9,
            "available_picks": 0,
            "picks": [
                _unavailable_pick(
                    s,
                    "GAME_CLOSED",
                    label,
                    "Pregame recommendations are closed once the event has started.",
                    matchup=game.get("matchup"),
                )
                for label in (
                    "MONEYLINE",
                    "POINT SPREAD",
                    "OVER / UNDER",
                    "HOME PLAYER PROP 1",
                    "HOME PLAYER PROP 2",
                    "HOME PLAYER PROP 3",
                    "AWAY PLAYER PROP 1",
                    "AWAY PLAYER PROP 2",
                    "AWAY PLAYER PROP 3",
                )
            ],
            "status": "PREGAME_CLOSED",
            "reasoning": [
                "Pregame recommendations are closed because this event is no longer a future matchup."
            ],
        }

    game_market = {row["type"]: row for row in _game_market_candidates(game)}
    picks: list[dict[str, Any]] = []
    for market_type, label in (
        ("moneyline", "MONEYLINE"),
        ("spread", "POINT SPREAD"),
        ("total", "OVER / UNDER"),
    ):
        row = game_market.get(market_type)
        if row:
            picks.append(row)
        else:
            picks.append(_unavailable_pick(
                s,
                "GAME_PROP",
                label,
                f"No fresh two-sided {label.lower()} quote passed the evidence checks for this matchup.",
                matchup=game.get("matchup"),
            ))

    matched = None
    try:
        d = date_cls.fromisoformat(str(game.get("date") or _pacific_today()))
        matched = _match_odds(game, _odds(s, d))
    except Exception:
        matched = None

    try:
        payload = _props_for_game(s, game, matched)
        raw_props = payload.get("props") or []
    except Exception:
        raw_props = []

    home, away = str(game.get("home") or ""), str(game.get("away") or "")
    by_side: dict[str, list[dict[str, Any]]] = {"HOME": [], "AWAY": []}
    for prop in raw_props:
        team, side, source = _roster_side_for_player(
            s,
            str(prop.get("player") or ""),
            home,
            away,
        )
        if not side:
            continue
        row = _prop_candidate(
            game,
            prop,
            team=team,
            team_side=side,
            roster_source=source,
        )
        if row:
            by_side[side].append(row)

    for rows in by_side.values():
        rows.sort(
            key=lambda row: float(row.get("probability") or 0.0),
            reverse=True,
        )

    for side, team in (("HOME", home), ("AWAY", away)):
        chosen: list[dict[str, Any]] = []
        used_players: set[str] = set()
        # Prefer three distinct players, then allow a second market for a verified
        # player only when that is the only way to reach the requested coverage.
        for row in by_side[side]:
            player_key = _norm(row.get("player"))
            if player_key in used_players:
                continue
            chosen.append(row)
            used_players.add(player_key)
            if len(chosen) == 3:
                break
        if len(chosen) < 3:
            for row in by_side[side]:
                if row in chosen:
                    continue
                chosen.append(row)
                if len(chosen) == 3:
                    break

        picks.extend(chosen)
        while len(chosen) < 3:
            index = len(chosen) + 1
            placeholder = _unavailable_pick(
                s,
                "PLAYER_PROP",
                f"{side} PLAYER PROP {index}",
                (
                    f"A {index}/3 verified {team} player prop is unavailable. "
                    "The app requires a fresh paired price plus a verified roster match and will not guess the player's team."
                ),
                matchup=game.get("matchup"),
            )
            placeholder["team"] = team
            placeholder["team_side"] = side
            picks.append(placeholder)
            chosen.append(placeholder)

    available_count = sum(1 for row in picks if row.get("available"))
    return {
        "sport": s,
        "event_id": event_id,
        "date": game.get("date"),
        "event_time": game.get("event_time"),
        "matchup": game.get("matchup"),
        "requested_picks": 9,
        "available_picks": available_count,
        "breakdown": {
            "moneyline": 1,
            "point_spread": 1,
            "over_under": 1,
            "home_player_props": 3,
            "away_player_props": 3,
        },
        "picks": picks,
        "status": "OK" if available_count == 9 else "PARTIAL_VERIFIED_COVERAGE",
        "reasoning": [
            "The first three slots are the fresh moneyline, point spread and over/under recommendations for this matchup.",
            "The next three slots are player props verified against the home-team roster; the final three are verified against the away-team roster.",
            "Player-prop sides require a recent paired sportsbook quote and de-vigged probability. Team assignment requires a current ESPN roster match.",
            "Any missing bookmaker evidence, timestamp, line, recommended side or roster match stays visibly unavailable rather than being replaced with a guess.",
        ],
    }


@app.get("/api/v1/picks/best12", include_in_schema=False)
@app.get("/v1/picks/best12")
def best12(date: str | None = None):
    try:
        return _best12(date)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@app.get("/api/v1/parlays/best3", include_in_schema=False)
@app.get("/v1/parlays/best3")
def best_three_leg_parlays(date: str | None = None):
    try:
        return _best_three_leg_parlays(date)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@app.get("/api/v1/games/{sport}/{event_id}/best9", include_in_schema=False)
@app.get("/v1/games/{sport}/{event_id}/best9")
def best_nine_game_picks(
    sport: str,
    event_id: str,
    date: str | None = None,
):
    try:
        return _best9_for_game(sport, event_id, date)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


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

            hp = (game.get("home_win_probability")
                  if game.get("probability_source") == "signed_promoted_trained_model"
                  else market.get("home_probability"))
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
            if per_sport_prop_events[sport] < 3:
                per_sport_prop_events[sport] += 1
                try:
                    matched_for_props = (
                        {"id": oid}
                        if oid and _primary_prop_provider_ready()
                        else None
                    )
                    payload = _props_for_game(
                        sport,
                        game,
                        matched_for_props,
                    )
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
                                "player": p.get("player"),
                                "market": p.get("market"),
                                "side": p.get("recommended_side"),
                                "line": p.get("line"),
                                "probability": round(
                                    float(p["market_probability"]), 6
                                ),
                                "probability_method": p.get("probability_method"),
                                "book_count": p.get("book_count"),
                                "contributing_books": p.get("contributing_books") or [],
                                "best_available_book": p.get("best_available_book"),
                                "best_available_price": p.get("best_available_price"),
                                "as_of": p.get("best_price_last_update") or p.get("last_update"),
                                "reason": p.get("reason"),
                                "model_state": p.get("model_state"),
                            })
                except Exception:
                    pass

        candidate_sports = {str(x.get("sport") or "") for x in candidates}
        if (
            len(candidates) >= target_count
            and set(SPORTS).issubset(candidate_sports)
        ):
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
        "selection_basis": "FRESH_VALIDATED_MARKETS_AND_PROPS_WITH_DIVERSIFICATION_AND_NO_SYNTHETIC_LEGS",
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


@app.get("/api/v1/data/external-providers", include_in_schema=False)
@app.get("/v1/data/external-providers")
def external_provider_status():
    rotation = os.getenv("CREDENTIAL_ROTATION_CONFIRMED", "").strip().lower() == "true"
    return {
        "odds_api_net": odds_api_net_status(),
        "the_odds_api": {
            "configured": bool(os.getenv("ODDS_API_KEY", "").strip()) and rotation,
            "credential_env": "ODDS_API_KEY",
        },
        "sportradar": {
            "configured": bool(os.getenv("SPORTRADAR_API_KEY", "").strip()) and rotation,
            "credential_env": "SPORTRADAR_API_KEY",
            "role": "optional verification/feed adapter; not allowed to bypass v8 promotion gates",
        },
        "draftfast": {
            "runtime_role": "optional DFS optimizer only",
            "prediction_model": False,
            "wager_execution": False,
        },
        "fanduel": {
            "direct_unofficial_client_enabled": False,
            "normalized_bookmaker_source": "odds-api.net when configured",
        },
    }


@app.get("/api/parlays/multisport", include_in_schema=False)
@app.get("/api/v1/parlays/multisport", include_in_schema=False)
@app.get("/v1/parlays/multisport")
def multisport_parlays(legs: int = Query(7), date: str | None = None):
    try:
        return _build_multisport_parlay(legs, date)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


# Register on the canonical app used by existing Render start commands too.
from evidence.runtime import (
    SignalEvidenceMiddleware,
    router as evidence_router,
    storage_status as evidence_storage_status,
)

app.add_middleware(SignalEvidenceMiddleware)
app.include_router(evidence_router)
