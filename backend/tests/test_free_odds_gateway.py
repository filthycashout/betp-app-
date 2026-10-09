from __future__ import annotations

from datetime import datetime, timedelta, timezone

import free_odds_gateway as gateway
from evidence import market_snapshot_store


def _event(source: str, book: str, when: datetime):
    return {
        "id": f"{source}-1",
        "sport": "NFL",
        "home_team": "Seattle Seahawks",
        "away_team": "San Francisco 49ers",
        "commence_time": when.isoformat(),
        "market_source": source,
        "bookmakers": [{
            "key": book,
            "title": book,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "markets": [{
                "key": "h2h",
                "outcomes": [
                    {"name": "Seattle Seahawks", "price": -120},
                    {"name": "San Francisco 49ers", "price": 110},
                ],
            }],
        }],
    }


def test_gateway_merges_espn_and_oddswrap(monkeypatch):
    when = datetime.now(timezone.utc) + timedelta(hours=12)
    espn = _event("ESPN_SCOREBOARD_ODDS", "espn", when)
    wrap = _event("ODDSWRAP", "draftkings", when)
    monkeypatch.setattr(gateway, "_oddswrap_game_events", lambda sport, day: [wrap])
    monkeypatch.setattr(gateway, "_sx_secondary_signal", lambda sport: {"available": True, "source": "SX_BET"})
    monkeypatch.setattr(gateway, "record_market_snapshot", lambda event, fetched_at=None: {
        "record_sha256": "a" * 64,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "event_time_utc": when.isoformat(),
    })
    rows = gateway.game_events("NFL", when.astimezone(gateway.PACIFIC).date(), [espn])
    assert len(rows) == 1
    assert rows[0]["market_source"] == "PHILTHY_FREE_ODDS_GATEWAY"
    assert {b["key"] for b in rows[0]["bookmakers"]} == {"espn", "draftkings"}
    assert rows[0]["gateway"]["book_count"] == 2
    assert rows[0]["snapshot_evidence"]["chronology_valid"] is True


def test_snapshot_rejects_post_event_fetch(tmp_path, monkeypatch):
    monkeypatch.setattr(market_snapshot_store, "SNAPSHOT_ROOT", tmp_path)
    monkeypatch.setattr(market_snapshot_store, "_ensure_database", lambda: False)
    event_time = datetime.now(timezone.utc) + timedelta(minutes=5)
    event = {
        "sport": "NBA", "id": "1", "home_team": "A", "away_team": "B",
        "commence_time": event_time.isoformat(), "bookmakers": [],
    }
    assert market_snapshot_store.record_market_snapshot(
        event, fetched_at=event_time + timedelta(seconds=1)
    ) is None
    good = market_snapshot_store.record_market_snapshot(
        event, fetched_at=event_time - timedelta(seconds=1)
    )
    assert good is not None
    assert len(good["record_sha256"]) == 64


def test_prop_market_mapping_is_explicit():
    assert gateway._prop_key("MLB", "Batter Props Hits O/U") == "batter_hits"
    assert gateway._prop_key("NBA", "Points + Rebounds + Assists") == "player_points_rebounds_assists"
