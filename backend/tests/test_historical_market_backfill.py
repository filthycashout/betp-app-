from __future__ import annotations

from datetime import datetime, timezone

import pytest

from training.historical_market_backfill import (
    BackfillBlocked,
    estimated_credits,
    fetch_featured_snapshot,
    normalize_featured,
)


def test_historical_credit_estimate_matches_documented_multiplier():
    assert estimated_credits(["h2h"], ["us"]) == 10
    assert estimated_credits(["h2h", "spreads", "totals"], ["us"]) == 30
    assert estimated_credits(["h2h", "spreads"], ["us", "uk"], requests_count=2) == 80


def test_dry_run_never_requires_api_key_or_paid_enable(monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    monkeypatch.delenv("ODDS_API_NET_KEY", raising=False)
    monkeypatch.delenv("ODDS_HISTORICAL_BACKFILL_ENABLED", raising=False)
    result = fetch_featured_snapshot(
        "NFL",
        "2026-09-01T18:00:00Z",
        regions=["us"],
        markets=["h2h", "spreads", "totals"],
        execute=False,
    )
    assert result["status"] == "DRY_RUN"
    assert result["plan"]["estimated_max_credits"] == 30
    assert result["plan"]["api_key_configured"] is False


def test_execute_requires_explicit_paid_backfill_enable(monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "test")
    monkeypatch.delenv("ODDS_HISTORICAL_BACKFILL_ENABLED", raising=False)
    with pytest.raises(BackfillBlocked, match="acknowledge paid historical usage"):
        fetch_featured_snapshot(
            "NFL",
            "2026-09-01T18:00:00Z",
            regions=["us"],
            markets=["h2h"],
            execute=True,
        )


def test_normalizer_devigs_and_excludes_post_start_snapshots():
    snapshot = {
        "timestamp": "2026-09-01T18:00:00Z",
        "data": [
            {
                "id": "game-1",
                "commence_time": "2026-09-01T20:00:00Z",
                "home_team": "Home",
                "away_team": "Away",
                "bookmakers": [
                    {
                        "key": "book",
                        "last_update": "2026-09-01T17:59:00Z",
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": "Home", "price": 1.8},
                                    {"name": "Away", "price": 2.1},
                                ],
                            },
                            {
                                "key": "spreads",
                                "outcomes": [
                                    {"name": "Home", "price": 1.91, "point": -2.5},
                                    {"name": "Away", "price": 1.91, "point": 2.5},
                                ],
                            },
                            {
                                "key": "totals",
                                "outcomes": [
                                    {"name": "Over", "price": 1.91, "point": 44.5},
                                    {"name": "Under", "price": 1.91, "point": 44.5},
                                ],
                            },
                        ],
                    }
                ],
            },
            {
                "id": "already-started",
                "commence_time": "2026-09-01T17:00:00Z",
                "home_team": "Old Home",
                "away_team": "Old Away",
                "bookmakers": [],
            },
        ],
    }
    rows = normalize_featured(snapshot, datetime(2026, 9, 1, 18, tzinfo=timezone.utc), "NFL")
    assert len(rows) == 1
    row = rows[0]
    assert row["provider_event_id"] == "game-1"
    assert 0 < row["consensus_de_vig_home_probability"] < 1
    assert row["home_spread"] == -2.5
    assert row["consensus_total"] == 44.5
    assert row["promotion_eligible"] is False
