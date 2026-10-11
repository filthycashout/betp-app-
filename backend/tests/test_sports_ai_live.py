from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from sports_ai.config.settings import Settings
from sports_ai.live import run_live_all, run_live_sport
from sports_ai.orchestrator import SportsAIEngine

NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _engine(*, sharp: bool = True) -> SportsAIEngine:
    return SportsAIEngine(Settings(
        min_edge=0.03,
        min_market_quality=0.75,
        max_snapshot_age_seconds=900,
        market_weight=0.70,
        kelly_fraction=0.25,
        sharp_book_keys=("pinnacle",) if sharp else (),
        sharp_max_age_seconds=180,
    ))


def _odds_event() -> dict:
    return {
        "id": "odds-1",
        "home_team": "Home",
        "away_team": "Away",
        "commence_time": (NOW + timedelta(hours=2)).isoformat(),
        "market_source": "TEST_GATEWAY",
        "bookmakers": [{
            "key": "soft-book",
            "last_update": (NOW - timedelta(seconds=20)).isoformat(),
            "markets": [{
                "key": "h2h",
                "outcomes": [
                    {"name": "Home", "price": 110},
                    {"name": "Away", "price": -130},
                ],
            }],
        }],
    }


def _pinnacle_event() -> dict:
    return {
        "id": "pinnacle-1",
        "home_team": "Home",
        "away_team": "Away",
        "commence_time": (NOW + timedelta(hours=2)).isoformat(),
        "market_source": "THE_ODDS_API_V4",
        "bookmakers": [{
            "key": "pinnacle",
            "title": "Pinnacle",
            "last_update": (NOW - timedelta(seconds=15)).isoformat(),
            "markets": [{
                "key": "h2h",
                "outcomes": [
                    {"name": "Home", "price": -180},
                    {"name": "Away", "price": 160},
                ],
            }],
        }],
    }


def _backend(*, promoted: bool = True, provider_error: bool = False, pinnacle: bool = False):
    game = {
        "event_id": "game-1",
        "home": "Home",
        "away": "Away",
        "event_time": (NOW + timedelta(hours=2)).isoformat(),
    }
    event = _odds_event()

    def schedule(_sport, _day):
        if provider_error:
            raise RuntimeError("fixture provider failure")
        return [game]

    def odds(_sport, _day):
        return [event]

    def market(_event):
        return {
            "home_probability": 0.58,
            "away_probability": 0.42,
            "home_spread": -3.5,
            "total": 45.5,
        }

    def odds_key():
        if not pinnacle:
            raise RuntimeError("credential unavailable")
        return "secret-fixture-key"

    def json_call(url, *, params, timeout):
        assert params["bookmakers"] == "pinnacle"
        return [_pinnacle_event()]

    return SimpleNamespace(
        _pacific_today=lambda: date.today(),
        _schedule=schedule,
        _odds=odds,
        _matches_search_query=lambda q, g, s, d: q.lower() in (g["home"] + g["away"]).lower(),
        _match_odds=lambda g, rows: rows[0] if rows else None,
        _market=market,
        _odds_key=odds_key,
        _json=json_call,
        _timed=lambda name, fn: fn(),
        SPORT_KEYS={"NFL": "americanfootball_nfl", "NBA": "basketball_nba", "MLB": "baseball_mlb", "NHL": "icehockey_nhl"},
        PROMOTED_MODELS={"NFL": {"model_id": "fixture"}} if promoted else {},
        _promotion_gate_for=lambda sport: {"passed": promoted and sport == "NFL"},
        predict_home_probability=lambda artifact, features: 0.58,
        _runtime_mode_for=lambda sport: "PROMOTED_TRAINED_MODEL" if promoted and sport == "NFL" else "BASELINE_FALLBACK",
    )


def test_live_promoted_model_stays_blocked_when_sharp_credential_is_missing() -> None:
    result = run_live_sport(
        "NFL",
        date=NOW.date().isoformat(),
        backend=_backend(promoted=True, pinnacle=False),
        engine=_engine(),
    )
    row = result["decisions"][0]
    decision = row["decision"]
    assert row["promoted_model_contributed"] is True
    assert decision["selection"] == "Home"
    assert decision["soft_american_odds"] == 110
    assert decision["decision"]["eligible"] is False
    assert "SHARP_ANCHOR_UNVERIFIED" in decision["decision"]["reasons"]
    assert row["sharp_anchor"]["status"] == "SHARP_CREDENTIAL_UNAVAILABLE"
    assert result["execution_policy"]["automatic_wagering"] is False


def test_live_verified_pinnacle_anchor_unlocks_sharp_gate() -> None:
    result = run_live_sport(
        "NFL",
        date=NOW.date().isoformat(),
        backend=_backend(promoted=False, pinnacle=True),
        engine=_engine(),
    )
    row = result["decisions"][0]
    decision = row["decision"]
    assert row["sharp_anchor"]["verified"] is True
    assert decision["sharp_anchor_verified"] is True
    assert decision["market_anchor_kind"] == "PINNACLE_NO_VIG"
    assert decision["soft_american_odds"] == 110
    assert "SHARP_ANCHOR_UNVERIFIED" not in decision["decision"]["reasons"]
    assert decision["decision"]["eligible"] is True
    assert result["execution_policy"]["verified_sharp_anchor_available"] is True
    assert result["execution_policy"]["automatic_wagering"] is False


def test_live_sharp_book_can_be_disabled_explicitly() -> None:
    result = run_live_sport(
        "NFL",
        date=NOW.date().isoformat(),
        backend=_backend(promoted=False, pinnacle=True),
        engine=_engine(sharp=False),
    )
    row = result["decisions"][0]
    assert row["sharp_anchor"]["status"] == "SHARP_BOOK_ALLOWLIST_EMPTY"
    assert row["decision"]["decision"]["eligible"] is False


def test_live_provider_failure_is_reported_without_fabricating_decisions() -> None:
    result = run_live_sport(
        "NFL",
        date=NOW.date().isoformat(),
        backend=_backend(provider_error=True),
        engine=_engine(),
    )
    assert result["status"] == "PROVIDER_UNAVAILABLE"
    assert result["decisions"] == []
    assert result["error_type"] == "RuntimeError"


def test_live_all_keeps_four_sport_shape() -> None:
    backend = _backend(promoted=False, pinnacle=False)
    backend.PROMOTED_MODELS = {}
    result = run_live_all(
        date=NOW.date().isoformat(),
        backend=backend,
        engine=_engine(),
    )
    assert set(result) == {"MLB", "NHL", "NBA", "NFL"}
