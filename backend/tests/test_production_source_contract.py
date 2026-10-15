from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from training import evidence_pipeline as ep
from training import prop_evidence_pipeline as props


def test_training_evidence_defaults_to_canonical_floot_api():
    assert ep.PRODUCTION_BASE_URL == "https://philthyparleys.floot.app/_api"
    assert ep.normalize_base_url("https://philthyparleys.floot.app") == ep.PRODUCTION_BASE_URL
    assert ep.normalize_base_url(ep.PRODUCTION_BASE_URL + "/") == ep.PRODUCTION_BASE_URL


@pytest.mark.parametrize(
    "url",
    [
        "https://philthysports-powerhouse.onrender.com",
        "https://philthysports-powerhouse-v8.onrender.com",
        "https://philthysports-api-v9.onrender.com",
        "https://philthysports-mcp-v1.onrender.com/mcp",
    ],
)
def test_training_evidence_rejects_retired_production_hosts(url):
    with pytest.raises(ValueError, match="Retired"):
        ep.normalize_base_url(url)


def test_capture_uses_floot_namespace_and_keeps_props_off_by_default(tmp_path, monkeypatch):
    seen = []

    def respond(url):
        seen.append(url)
        return {"games": []}

    monkeypatch.setattr(ep, "_json", respond)
    ep.capture("https://philthyparleys.floot.app", tmp_path, days=4)
    assert len(seen) == 1
    parsed = ep.urllib.parse.urlsplit(seen[0])
    assert parsed.path == "/_api/v1/today"
    assert ep.urllib.parse.parse_qs(parsed.query) == {
        "include_props": ["false"],
        "props_limit": ["0"],
        "days": ["4"],
    }


def test_prop_capture_is_research_only_and_pregame(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    payload = {
        "games": [
            {
                "sport": "MLB",
                "event_id": "game-1",
                "event_time": (now + timedelta(hours=2)).isoformat(),
                "home": "Home",
                "away": "Away",
                "props_to_watch": [
                    {
                        "player": "Verified Player",
                        "market": "pitcher_strikeouts",
                        "line": 6.5,
                        "recommended_side": "UNDER",
                        "market_probability": 0.5535,
                        "probability_method": "same_book_two_sided_devig",
                        "best_available_price": -138,
                        "best_available_book": "verified_book",
                        "best_price_last_update": now.isoformat(),
                        "contributing_books": ["verified_book", "second_book"],
                        "book_count": 2,
                        "freshness_basis": ["provider_timestamp"],
                        "provider_timestamp_verified": True,
                        "model_state": "MARKET_ONLY_UNTIL_VALIDATED_PROP_MODEL",
                    }
                ],
            },
            {
                "sport": "NFL",
                "event_id": "already-started",
                "event_time": (now - timedelta(minutes=1)).isoformat(),
                "props_to_watch": [
                    {"player": "Must Be Dropped", "market": "player_pass_yds"}
                ],
            },
        ]
    }
    seen = []

    def respond(url):
        seen.append(url)
        return payload

    monkeypatch.setattr(props, "_json", respond)
    manifest = props.capture_props(ep.PRODUCTION_BASE_URL, tmp_path, days=1, props_limit=20)
    rows_path = tmp_path / manifest["rows_file"]["name"]
    rows = [json.loads(line) for line in rows_path.read_text().splitlines() if line.strip()]

    assert len(rows) == 1
    row = rows[0]
    assert row["player"] == "Verified Player"
    assert row["market_probability"] == pytest.approx(0.5535)
    assert row["model_probability"] is None
    assert row["model_edge"] is None
    assert row["model_ev"] is None
    assert row["promotion_eligible"] is False
    assert row["automatic_wagering"] is False
    assert manifest["promotion_eligible"] is False
    assert manifest["automatic_wagering"] is False

    query = ep.urllib.parse.parse_qs(ep.urllib.parse.urlsplit(seen[0]).query)
    assert query == {"include_props": ["true"], "props_limit": ["20"], "days": ["1"]}
