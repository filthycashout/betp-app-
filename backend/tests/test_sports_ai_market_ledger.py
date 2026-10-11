from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sports_ai.config.settings import Settings
from sports_ai.ingestion.market import moneyline_candidate_from_validated_market
from sports_ai.orchestrator import SportsAIEngine
from sports_ai.tracking.ledger import build_closing_record, build_recommendation_record


def _game(now: datetime) -> dict:
    return {
        "event_id": "fixture-event",
        "event_time": (now + timedelta(hours=2)).isoformat(),
        "home": "Fixture Home",
        "away": "Fixture Away",
    }


def _market(now: datetime) -> dict:
    return {
        "freshness_verified": True,
        "provider_timestamp_verified": True,
        "observed_at_verified": False,
        "moneyline_pick": "Fixture Home",
        "moneyline_pick_probability": 0.56,
        "moneyline_best_price": 110,
        "moneyline_best_book": "fixture-soft-book",
        "moneyline_last_update": (now - timedelta(seconds=30)).isoformat(),
    }


def _engine() -> SportsAIEngine:
    return SportsAIEngine(
        Settings(
            min_edge=0.03,
            min_market_quality=0.75,
            max_snapshot_age_seconds=900,
            market_weight=0.70,
            kelly_fraction=0.25,
        )
    )


def test_consensus_is_not_silently_labeled_sharp() -> None:
    now = datetime(2026, 10, 11, 20, tzinfo=timezone.utc)
    candidate = moneyline_candidate_from_validated_market(
        sport="NFL",
        game=_game(now),
        market=_market(now),
        context_ready=True,
        source_health_passed=True,
        prediction_time=now,
        actionable=True,
    )
    assert candidate.market_anchor_kind == "DEVIG_CONSENSUS"
    assert candidate.sharp_anchor_verified is False
    result = _engine().evaluate_candidate(candidate)
    assert result["decision"]["eligible"] is False
    assert "SHARP_ANCHOR_UNVERIFIED" in result["decision"]["reasons"]


def test_fresh_explicit_sharp_anchor_unlocks_sharp_gate() -> None:
    now = datetime(2026, 10, 11, 20, tzinfo=timezone.utc)
    candidate = moneyline_candidate_from_validated_market(
        sport="NFL",
        game=_game(now),
        market=_market(now),
        context_ready=True,
        source_health_passed=True,
        prediction_time=now,
        actionable=True,
        sharp_anchor={
            "source": "Pinnacle",
            "selection": "Fixture Home",
            "no_vig": True,
            "probability": 0.60,
            "observed_at": (now - timedelta(seconds=20)).isoformat(),
        },
    )
    result = _engine().evaluate_candidate(candidate)
    assert result["sharp_anchor_verified"] is True
    assert result["market_anchor_kind"] == "PINNACLE_NO_VIG"
    assert "SHARP_ANCHOR_UNVERIFIED" not in result["decision"]["reasons"]


def test_sharp_anchor_requires_matching_no_vig_selection() -> None:
    now = datetime(2026, 10, 11, 20, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="no-vig"):
        moneyline_candidate_from_validated_market(
            sport="NFL",
            game=_game(now),
            market=_market(now),
            context_ready=True,
            source_health_passed=True,
            prediction_time=now,
            sharp_anchor={
                "source": "Pinnacle",
                "selection": "Fixture Home",
                "probability": 0.60,
                "observed_at": now.isoformat(),
            },
        )
    with pytest.raises(ValueError, match="selection"):
        moneyline_candidate_from_validated_market(
            sport="NFL",
            game=_game(now),
            market=_market(now),
            context_ready=True,
            source_health_passed=True,
            prediction_time=now,
            sharp_anchor={
                "source": "Pinnacle",
                "selection": "Fixture Away",
                "no_vig": True,
                "probability": 0.60,
                "observed_at": now.isoformat(),
            },
        )


def test_stale_validated_market_is_rejected_before_decision() -> None:
    now = datetime(2026, 10, 11, 20, tzinfo=timezone.utc)
    market = _market(now)
    market["moneyline_last_update"] = (now - timedelta(minutes=10)).isoformat()
    with pytest.raises(ValueError, match="stale"):
        moneyline_candidate_from_validated_market(
            sport="MLB",
            game=_game(now),
            market=market,
            context_ready=True,
            source_health_passed=True,
            prediction_time=now,
        )


def test_market_conditioned_model_is_not_blended_twice() -> None:
    now = datetime(2026, 10, 11, 20, tzinfo=timezone.utc)
    candidate = moneyline_candidate_from_validated_market(
        sport="NBA",
        game=_game(now),
        market=_market(now),
        context_ready=True,
        source_health_passed=True,
        prediction_time=now,
        actionable=False,
        model_prob=0.63,
        model_promotion_passed=True,
        model_includes_market=True,
    )
    result = _engine().evaluate_candidate(candidate)
    assert result["final_probability"] == pytest.approx(0.63)
    assert result["probability_source"] == "PROMOTED_MARKET_CONDITIONED_MODEL"
    assert result["probability_method"] == "promoted_calibrated_model_already_conditions_on_market"


def test_append_only_ledger_records_are_deterministic_and_point_in_time() -> None:
    now = datetime(2026, 10, 11, 20, tzinfo=timezone.utc)
    game = _game(now)
    candidate = moneyline_candidate_from_validated_market(
        sport="NHL",
        game=game,
        market=_market(now),
        context_ready=True,
        source_health_passed=True,
        prediction_time=now,
        actionable=False,
    )
    result = _engine().evaluate_candidate(candidate)
    first = build_recommendation_record(
        result,
        as_of=now,
        event_time=game["event_time"],
    )
    second = build_recommendation_record(
        result,
        as_of=now,
        event_time=game["event_time"],
    )
    assert first["recommendation_id"] == second["recommendation_id"]

    close = build_closing_record(
        recommendation_id=first["recommendation_id"],
        close_american=100,
        close_fair_probability=0.58,
        observed_at=now + timedelta(hours=1, minutes=50),
        event_time=game["event_time"],
    )
    assert len(close["record_sha256"]) == 64

    with pytest.raises(ValueError, match="before event_time"):
        build_recommendation_record(
            result,
            as_of=now + timedelta(hours=3),
            event_time=game["event_time"],
        )
