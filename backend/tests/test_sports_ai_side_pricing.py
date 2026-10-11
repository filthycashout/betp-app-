from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sports_ai.config.settings import Settings
from sports_ai.ingestion.market import moneyline_candidate_from_event
from sports_ai.ingestion.odds import moneyline_snapshot_from_event
from sports_ai.orchestrator import SportsAIEngine

NOW = datetime(2026, 10, 11, 20, tzinfo=timezone.utc)


def _book(name: str, home_price: int, away_price: int, *, age_seconds: int = 20) -> dict:
    return {
        "key": name,
        "last_update": (NOW - timedelta(seconds=age_seconds)).isoformat(),
        "markets": [{
            "key": "h2h",
            "outcomes": [
                {"name": "Home", "price": home_price},
                {"name": "Away", "price": away_price},
            ],
        }],
    }


def _observed_book(name: str, home_price: int, away_price: int, *, age_seconds: int = 20) -> dict:
    return {
        "key": name,
        "observed_at": (NOW - timedelta(seconds=age_seconds)).isoformat(),
        "markets": [{
            "key": "h2h",
            "outcomes": [
                {"name": "Home", "price": home_price},
                {"name": "Away", "price": away_price},
            ],
        }],
    }


def _event(*books: dict) -> dict:
    return {
        "id": "fixture-event",
        "home_team": "Home",
        "away_team": "Away",
        "commence_time": (NOW + timedelta(hours=2)).isoformat(),
        "bookmakers": list(books),
    }


def _game() -> dict:
    return {
        "event_id": "fixture-event",
        "home": "Home",
        "away": "Away",
        "event_time": (NOW + timedelta(hours=2)).isoformat(),
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


def test_side_complete_snapshot_keeps_best_price_for_each_team() -> None:
    snapshot = moneyline_snapshot_from_event(
        _event(
            _book("book-a", -150, 130),
            _book("book-b", -140, 125),
        ),
        now=NOW,
    )
    assert snapshot["status"] == "OK"
    assert snapshot["home_best_price"] == -140
    assert snapshot["home_best_book"] == "book-b"
    assert snapshot["away_best_price"] == 130
    assert snapshot["away_best_book"] == "book-a"
    assert snapshot["home_probability"] + snapshot["away_probability"] == pytest.approx(1.0)
    assert snapshot["book_count"] == 2


def test_model_can_select_opposite_side_without_reusing_consensus_price() -> None:
    event = _event(
        _book("book-a", -150, 130),
        _book("book-b", -140, 125),
    )
    snapshot = moneyline_snapshot_from_event(event, now=NOW)
    assert snapshot["home_probability"] > 0.5

    candidate = moneyline_candidate_from_event(
        sport="NFL",
        game=_game(),
        odds_event=event,
        selection="Away",
        context_ready=True,
        source_health_passed=True,
        prediction_time=NOW,
        actionable=False,
        model_prob=0.60,
        model_promotion_passed=True,
        model_includes_market=True,
    )
    assert candidate.selection == "Away"
    assert candidate.soft_american_odds == 130
    assert candidate.market_anchor_prob == pytest.approx(snapshot["away_probability"])

    result = _engine().evaluate_candidate(candidate)
    assert result["selection"] == "Away"
    assert result["soft_american_odds"] == 130
    assert result["final_probability"] == pytest.approx(0.60)
    assert result["probability_source"] == "PROMOTED_MARKET_CONDITIONED_MODEL"


def test_selected_price_quality_uses_that_books_timestamp_basis() -> None:
    event = _event(
        _book("provider-book", -110, -110),
        _observed_book("observed-soft", -105, 120),
    )
    snapshot = moneyline_snapshot_from_event(event, now=NOW)
    assert snapshot["provider_timestamp_verified"] is True
    assert snapshot["observed_at_verified"] is True
    assert snapshot["away_best_book"] == "observed-soft"
    assert snapshot["away_best_price_freshness_basis"] == "fresh_fetch_observed_at"

    candidate = moneyline_candidate_from_event(
        sport="NHL",
        game=_game(),
        odds_event=event,
        selection="Away",
        context_ready=True,
        source_health_passed=True,
        prediction_time=NOW,
        actionable=False,
    )
    assert candidate.market_quality == pytest.approx(0.80)


def test_stale_book_is_excluded_without_poisoning_fresh_pair() -> None:
    snapshot = moneyline_snapshot_from_event(
        _event(
            _book("fresh", -120, 105, age_seconds=20),
            _book("stale", 250, -300, age_seconds=601),
        ),
        now=NOW,
    )
    assert snapshot["status"] == "OK"
    assert snapshot["books_used"] == ["fresh"]
    assert snapshot["home_best_book"] == "fresh"
    assert snapshot["away_best_book"] == "fresh"


def test_one_sided_or_post_start_event_fails_closed() -> None:
    one_sided = _event({
        "key": "book-a",
        "last_update": NOW.isoformat(),
        "markets": [{"key": "h2h", "outcomes": [{"name": "Home", "price": -120}]}],
    })
    assert moneyline_snapshot_from_event(one_sided, now=NOW)["status"] == "NO_FRESH_TWO_SIDED_MONEYLINE"

    started = _event(_book("book-a", -120, 105))
    started["commence_time"] = NOW.isoformat()
    assert moneyline_snapshot_from_event(started, now=NOW)["status"] == "NO_VERIFIED_PREGAME_EVENT"


def test_unknown_selection_is_rejected() -> None:
    with pytest.raises(ValueError, match="selection"):
        moneyline_candidate_from_event(
            sport="MLB",
            game=_game(),
            odds_event=_event(_book("book-a", -120, 105)),
            selection="Third Team",
            context_ready=True,
            source_health_passed=True,
            prediction_time=NOW,
            actionable=False,
        )
