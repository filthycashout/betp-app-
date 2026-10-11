from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from sports_ai.config.settings import Settings
from sports_ai.live import run_live_all, run_live_sport
from sports_ai.orchestrator import SportsAIEngine

NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _engine() -> SportsAIEngine:
    return SportsAIEngine(Settings(
        min_edge=0.03,
        min_market_quality=0.75,
        max_snapshot_age_seconds=900,
        market_weight=0.70,
        kelly_fraction=0.25,
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
                    {"name": "Home", "price": -150},
                    {"name": "Away", "price": 130},
                ],
            }],
        }],
    }


def _backend(*, promoted: bool = True, provider_error: bool = False):
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

    return SimpleNamespace(
        _pacific_today=lambda: date.today(),
        _schedule=schedule,
        _odds=odds,
        _matches_search_query=lambda q, g, s, d: q.lower() in (g["home"] + g["away"]).lower(),
        _match_odds=lambda g, rows: rows[0] if rows else None,
        _market=market,
        PROMOTED_MODELS={"NFL": {"model_id": "fixture"}} if promoted else {},
        _promotion_gate_for=lambda sport: {"passed": promoted},
        predict_home_probability=lambda artifact, features: 0.42,
        _runtime_mode_for=lambda sport: "PROMOTED_TRAINED_MODEL" if promoted else "BASELINE_FALLBACK",
    )


def test_live_promoted_model_can_pick_away_with_away_price_but_stays_sharp_blocked() -> None:
    result = run_live_sport(
        "NFL",
        date=NOW.date().isoformat(),
        backend=_backend(promoted=True),
        engine=_engine(),
    )
    row = result["decisions"][0]
    decision = row["decision"]
    assert row["promoted_model_contributed"] is True
    assert decision["selection"] == "Away"
    assert decision["soft_american_odds"] == 130
    assert decision["final_probability"] == pytest.approx(0.58)
    assert decision["probability_source"] == "PROMOTED_MARKET_CONDITIONED_MODEL"
    assert decision["decision"]["eligible"] is False
    assert "SHARP_ANCHOR_UNVERIFIED" in decision["decision"]["reasons"]
    assert result["execution_policy"]["automatic_wagering"] is False


def test_live_baseline_ignores_unpromoted_model_path() -> None:
    result = run_live_sport(
        "NFL",
        date=NOW.date().isoformat(),
        backend=_backend(promoted=False),
        engine=_engine(),
    )
    row = result["decisions"][0]
    decision = row["decision"]
    assert row["promoted_model_contributed"] is False
    assert decision["selection"] == "Home"
    assert decision["probability_source"] == "MARKET_BASELINE"
    assert decision["model_probability"] is None


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
    backend = _backend(promoted=False)
    backend.PROMOTED_MODELS = {}
    result = run_live_all(
        date=NOW.date().isoformat(),
        backend=backend,
        engine=_engine(),
    )
    assert set(result) == {"MLB", "NHL", "NBA", "NFL"}
