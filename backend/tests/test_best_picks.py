from datetime import datetime, timedelta, timezone

import app as runtime
from fastapi.testclient import TestClient

client = TestClient(runtime.app)


def _game(sport="NFL", event_id="1"):
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    return {
        "event_id": event_id,
        "sport": sport,
        "event_time": future,
        "event_time_pacific": future,
        "date": future[:10],
        "home": f"{sport} Home",
        "away": f"{sport} Away",
        "matchup": f"{sport} Away @ {sport} Home",
        "model_status": "EVIDENCE_GATED_HYBRID_MARKET_FORM_FALLBACK",
        "market": {
            "home_probability": 0.56,
            "away_probability": 0.44,
            "moneyline_pick": f"{sport} Home",
            "moneyline_pick_probability": 0.56,
            "moneyline_best_price": -125,
            "moneyline_best_book": "book-a",
            "moneyline_last_update": datetime.now(timezone.utc).isoformat(),
            "home_spread": -2.5,
            "away_spread": 2.5,
            "spread_pick": f"{sport} Away",
            "spread_pick_probability": 0.53,
            "spread_best_price": -105,
            "spread_best_book": "book-a",
            "spread_last_update": datetime.now(timezone.utc).isoformat(),
            "total": 45.5,
            "total_pick": "OVER",
            "total_pick_probability": 0.52,
            "total_best_price": -108,
            "total_best_book": "book-a",
            "total_last_update": datetime.now(timezone.utc).isoformat(),
        },
    }


def _prop(game, player="Test Player", probability=0.61):
    return {
        "available": True,
        "sport": game["sport"],
        "event_id": game["event_id"],
        "event_time": game["event_time"],
        "event_time_pacific": game["event_time_pacific"],
        "date": game["date"],
        "matchup": game["matchup"],
        "category": "PLAYER_PROP",
        "type": "player_prop",
        "market_label": "PLAYER POINTS",
        "label": f"{player} OVER 20.5 player_points",
        "player": player,
        "line": 20.5,
        "selection": "OVER",
        "probability": probability,
        "best_available_book": "book-a",
        "best_available_price": -110,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "contributing_books": ["book-a"],
        "reason": "Fresh paired prices support the de-vigged side.",
    }


def test_new_best_pick_routes_are_registered():
    paths = {route.path for route in runtime.app.routes}
    assert "/v1/picks/best12" in paths
    assert "/v1/parlays/best3" in paths
    assert "/v1/games/{sport}/{event_id}/best9" in paths


def test_best12_has_fixed_four_four_four_shape(monkeypatch):
    games = []
    props = []
    for i, sport in enumerate(runtime.SPORTS, 1):
        game = _game(sport, str(i))
        games.extend(runtime._game_market_candidates(game))
        props.append(_prop(game, f"{sport} Player", 0.60 + i / 1000))

    monkeypatch.setattr(
        runtime,
        "_board_for_date",
        lambda d: {
            "date": d.isoformat(),
            "game_candidates": games,
            "prop_candidates": props,
        },
    )

    payload = runtime._best12("2035-01-01")
    assert len(payload["picks"]) == 12
    assert payload["breakdown"] == {
        "game_props": 4,
        "player_props": 4,
        "multisport_mix": 4,
    }
    assert [p.get("board_bucket") for p in payload["picks"][:4]] == ["GAME_PROP"] * 4
    assert [p.get("board_bucket") for p in payload["picks"][4:8]] == ["PLAYER_PROP"] * 4
    assert [p.get("board_bucket") for p in payload["picks"][8:]] == ["MULTISPORT_MIX"] * 4


def test_best3_returns_two_three_leg_slots_per_sport(monkeypatch):
    games = []
    props = []
    for i, sport in enumerate(runtime.SPORTS, 1):
        game = _game(sport, str(i))
        games.extend(runtime._game_market_candidates(game))
        props.extend([
            _prop(game, f"{sport} Player A", 0.64),
            _prop({**game, "event_id": f"{i}9"}, f"{sport} Player B", 0.58),
        ])

    monkeypatch.setattr(
        runtime,
        "_board_for_date",
        lambda d: {
            "date": d.isoformat(),
            "game_candidates": games,
            "prop_candidates": props,
        },
    )

    payload = runtime._best_three_leg_parlays("2035-01-01")
    assert len(payload["cards"]) == 8
    for sport in runtime.SPORTS:
        cards = [c for c in payload["cards"] if c["sport"] == sport]
        assert [c["rank"] for c in cards] == [1, 2]
        assert all(len(c["legs"]) in {0, 3} for c in cards)


def test_best9_keeps_exact_nine_slots_and_never_invents_missing_props(monkeypatch):
    game = _game("NFL", "88")
    monkeypatch.setattr(runtime, "game_detail", lambda *a, **k: dict(game))
    monkeypatch.setattr(runtime, "_odds", lambda *a, **k: [])
    monkeypatch.setattr(
        runtime,
        "_props_for_game",
        lambda *a, **k: {"props": [], "status": "NO_FRESH_MARKETS"},
    )

    payload = runtime._best9_for_game("NFL", "88", game["date"])
    assert len(payload["picks"]) == 9
    assert sum(1 for p in payload["picks"] if p["available"]) == 3
    assert all(
        p["available"] is False
        for p in payload["picks"][3:]
    )
    assert payload["status"] == "PARTIAL_VERIFIED_COVERAGE"
