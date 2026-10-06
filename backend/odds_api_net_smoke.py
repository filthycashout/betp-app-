from __future__ import annotations

from odds_api_net import normalize_event


def main() -> None:
    event = {
        "event_id": "nba-001",
        "sport": "basketball",
        "league": "NBA",
        "start_time": 1791266400,
        "home_team": "Home Team",
        "away_team": "Away Team",
        "last_capture": 1791262800,
    }
    snapshot = {
        "event_id": "nba-001",
        "as_of_ts_ms": 1791262800000,
        "items": [
            {"id": "1", "event_id": "nba-001", "bookmaker": "fanduel", "market_key": "moneyline", "type": "moneyline", "period": 0, "side": "home", "odds": 1.80, "is_available": True},
            {"id": "2", "event_id": "nba-001", "bookmaker": "fanduel", "market_key": "moneyline", "type": "moneyline", "period": 0, "side": "away", "odds": 2.10, "is_available": True},
            {"id": "3", "event_id": "nba-001", "bookmaker": "fanduel", "market_key": "spread", "market_group_id": "spread-main", "type": "spread", "period": 0, "side": "home", "line": "-3.5", "odds": 1.91, "is_available": True},
            {"id": "4", "event_id": "nba-001", "bookmaker": "fanduel", "market_key": "spread", "market_group_id": "spread-main", "type": "spread", "period": 0, "side": "away", "line": "3.5", "odds": 1.91, "is_available": True},
            {"id": "5", "event_id": "nba-001", "bookmaker": "fanduel", "market_key": "total", "market_group_id": "total-main", "type": "total", "period": 0, "side": "over", "line": "221.5", "odds": 1.91, "is_available": True},
            {"id": "6", "event_id": "nba-001", "bookmaker": "fanduel", "market_key": "total", "market_group_id": "total-main", "type": "total", "period": 0, "side": "under", "line": "221.5", "odds": 1.91, "is_available": True},
            {"id": "7", "event_id": "nba-001", "bookmaker": "fanduel", "market_key": "player total", "type": "total", "period": 0, "side": "over", "player_name": "Player A", "line": "24.5", "odds": 1.91, "is_available": True},
        ],
    }
    row = normalize_event(event, snapshot)
    assert row is not None
    assert row["market_source"] == "ODDS_API_NET"
    assert row["home_team"] == "Home Team"
    assert row["away_team"] == "Away Team"
    books = row["bookmakers"]
    assert len(books) == 1
    assert books[0]["title"] == "fanduel"
    markets = {market["key"]: market for market in books[0]["markets"]}
    assert set(markets) == {"h2h", "spreads", "totals"}
    assert len(markets["h2h"]["outcomes"]) == 2
    assert {outcome["name"] for outcome in markets["totals"]["outcomes"]} == {"Over", "Under"}
    assert all(outcome.get("price") is not None for market in markets.values() for outcome in market["outcomes"])
    print("odds_api_net_smoke: PASS")


if __name__ == "__main__":
    main()
