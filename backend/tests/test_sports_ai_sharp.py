from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from sports_ai.ingestion.market import moneyline_candidate_from_event
from sports_ai.ingestion.sharp import extract_sharp_moneyline_anchor, fetch_pinnacle_moneyline_anchor

NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _game() -> dict:
    return {
        "event_id": "game-1",
        "home": "Home",
        "away": "Away",
        "event_time": (NOW + timedelta(hours=2)).isoformat(),
    }


def _event(*books: dict) -> dict:
    return {
        "id": "provider-event",
        "home_team": "Home",
        "away_team": "Away",
        "commence_time": (NOW + timedelta(hours=2)).isoformat(),
        "market_source": "THE_ODDS_API_V4",
        "bookmakers": list(books),
    }


def _book(key: str, home: int, away: int, *, age_seconds: int = 20, observed_only: bool = False) -> dict:
    stamp_key = "observed_at" if observed_only else "last_update"
    return {
        "key": key,
        "title": key.title(),
        stamp_key: (NOW - timedelta(seconds=age_seconds)).isoformat(),
        "markets": [{
            "key": "h2h",
            "outcomes": [
                {"name": "Home", "price": home},
                {"name": "Away", "price": away},
            ],
        }],
    }


def test_verified_pinnacle_anchor_is_same_book_devigged_and_provider_timestamped() -> None:
    result = extract_sharp_moneyline_anchor(
        [_event(_book("pinnacle", -180, 160))],
        game=_game(),
        selection="Home",
        now=NOW,
    )
    assert result["verified"] is True
    anchor = result["anchor"]
    assert anchor["source"] == "pinnacle"
    assert anchor["no_vig"] is True
    assert anchor["timestamp_basis"] == "provider_timestamp"
    assert 0.60 < anchor["probability"] < 0.70


def test_observed_only_or_stale_sharp_quote_fails_closed() -> None:
    observed = extract_sharp_moneyline_anchor(
        [_event(_book("pinnacle", -180, 160, observed_only=True))],
        game=_game(),
        selection="Home",
        now=NOW,
    )
    assert observed["status"] == "SHARP_PROVIDER_TIMESTAMP_REQUIRED"
    stale = extract_sharp_moneyline_anchor(
        [_event(_book("pinnacle", -180, 160, age_seconds=181))],
        game=_game(),
        selection="Home",
        now=NOW,
        max_age_seconds=180,
    )
    assert stale["status"] == "SHARP_QUOTE_STALE"


def test_candidate_excludes_sharp_book_from_soft_price_pool() -> None:
    event = _event(
        _book("pinnacle", 125, -145),
        _book("soft-book", 110, -130),
    )
    sharp = extract_sharp_moneyline_anchor(
        [event],
        game=_game(),
        selection="Home",
        now=NOW,
    )["anchor"]
    candidate = moneyline_candidate_from_event(
        sport="NFL",
        game=_game(),
        odds_event=event,
        selection="Home",
        context_ready=True,
        source_health_passed=True,
        prediction_time=NOW,
        sharp_anchor=sharp,
    )
    assert candidate.sharp_anchor_verified is True
    assert candidate.soft_american_odds == 110
    assert candidate.market_anchor_kind == "PINNACLE_NO_VIG"


def test_pinnacle_fetch_uses_bookmaker_filter_and_never_returns_key() -> None:
    captured = {}

    def json_call(url, *, params, timeout):
        captured["url"] = url
        captured["params"] = dict(params)
        return [_event(_book("pinnacle", -180, 160))]

    runtime = SimpleNamespace(
        _odds_key=lambda: "secret-fixture-key",
        SPORT_KEYS={"NFL": "americanfootball_nfl"},
        _json=json_call,
        _timed=lambda name, fn: fn(),
    )
    result = fetch_pinnacle_moneyline_anchor(
        runtime,
        sport="NFL",
        game=_game(),
        selection="Home",
        now=NOW,
    )
    assert result["verified"] is True
    assert captured["params"]["bookmakers"] == "pinnacle"
    assert "regions" not in captured["params"]
    assert "secret-fixture-key" not in str(result)


def test_missing_credential_does_not_downgrade_to_unverified_sharp() -> None:
    runtime = SimpleNamespace(
        _odds_key=lambda: (_ for _ in ()).throw(RuntimeError("credential unavailable")),
        SPORT_KEYS={"NFL": "americanfootball_nfl"},
    )
    result = fetch_pinnacle_moneyline_anchor(
        runtime,
        sport="NFL",
        game=_game(),
        selection="Home",
        now=NOW,
    )
    assert result["verified"] is False
    assert result["status"] == "SHARP_CREDENTIAL_UNAVAILABLE"
    assert result["anchor"] is None
