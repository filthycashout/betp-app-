from __future__ import annotations

import app as backend


def _fake_games() -> dict:
    sports = ["NFL", "NBA", "MLB", "NHL"]
    games = []
    for index in range(16):
        sport = sports[index % len(sports)]
        home = f"{sport} Home {index}"
        away = f"{sport} Away {index}"
        home_probability = 0.70 - (index * 0.005)
        games.append(
            {
                "event_id": f"event-{index}",
                "sport": sport,
                "event_time": f"2026-10-02T{10 + (index % 10):02d}:00:00Z",
                "home": home,
                "away": away,
                "matchup": f"{away} @ {home}",
                "odds_event_id": None,
                "market": {
                    "home_probability": home_probability,
                    "away_probability": 1.0 - home_probability,
                    "home_spread": -2.5,
                    "away_spread": 2.5,
                    "spread_pick": home,
                    "spread_pick_probability": 0.56,
                    "total": 45.0,
                    "total_pick": "OVER" if index % 2 == 0 else "UNDER",
                    "total_pick_probability": 0.54,
                    "books_used": ["fixture_a", "fixture_b"],
                },
                "pick": home,
            }
        )
    return {"games": games}


def main() -> None:
    assert backend.health()["status"] == "ok"
    assert backend.root()["service"] == "PhilthySports Powerhouse"

    statuses = backend.model_status()
    assert set(statuses) == set(backend.SPORTS)
    for sport in backend.SPORTS:
        gate = statuses[sport]["promotion_gate"]
        if gate["passed"]:
            assert statuses[sport]["promoted_artifact_loaded"] is True
            assert statuses[sport]["runtime_mode"] == "PROMOTED_TRAINED_MODEL"
        else:
            assert statuses[sport]["runtime_mode"] == "EVIDENCE_GATED_HYBRID_MARKET_FORM_FALLBACK"

    registry = backend.model_registry()
    assert set(registry["sports"]) == set(backend.SPORTS)
    for sport in backend.SPORTS:
        assert registry["sports"][sport]["runtime_mode"] == statuses[sport]["runtime_mode"]

    for sport in backend.SPORTS:
        assert backend.PROP_MARKETS[sport], f"{sport} prop markets missing"
        assert backend.PROP_ALTERNATE_MARKETS[sport], f"{sport} alternate prop markets missing"
        assert backend.PROP_DEFAULT_LIVE_MARKETS[sport], f"{sport} default live prop markets missing"

    assert "batter_first_home_run" in backend.PROP_MARKETS["MLB"]
    assert "pitcher_record_a_win" in backend.PROP_MARKETS["MLB"]
    assert "pitcher_outs_alternate" in backend.PROP_ALTERNATE_MARKETS["MLB"]
    assert "player_first_basket" in backend.PROP_MARKETS["NBA"]
    assert "player_pass_yds_alternate" in backend.PROP_ALTERNATE_MARKETS["NFL"]
    assert "player_goal_scorer_first" in backend.PROP_MARKETS["NHL"]

    old_key = backend.os.environ.get("ODDS_API_KEY")
    old_rotation = backend.os.environ.get("CREDENTIAL_ROTATION_CONFIRMED")
    try:
        backend.os.environ["ODDS_API_KEY"] = "ci-placeholder-never-used"
        backend.os.environ.pop("CREDENTIAL_ROTATION_CONFIRMED", None)
        assert backend._primary_prop_provider_ready() is False
        capabilities = backend.prop_capabilities()
        assert capabilities["keyless_fallback_configured"] is True
        assert capabilities["keyless_fallback"]["credential_required"] is False
    finally:
        if old_key is None:
            backend.os.environ.pop("ODDS_API_KEY", None)
        else:
            backend.os.environ["ODDS_API_KEY"] = old_key
        if old_rotation is None:
            backend.os.environ.pop("CREDENTIAL_ROTATION_CONFIRMED", None)
        else:
            backend.os.environ["CREDENTIAL_ROTATION_CONFIRMED"] = old_rotation

    snapshot = {
        "teams": {
            "testhome": {
                "name": "Test Home",
                "games": 4,
                "wins": 3,
                "ties": 0,
                "points_for": 100.0,
                "points_against": 80.0,
            },
            "testaway": {
                "name": "Test Away",
                "games": 4,
                "wins": 1,
                "ties": 0,
                "points_for": 72.0,
                "points_against": 96.0,
            },
        },
        "completed_games": 8,
        "league_mean_abs_margin": 7.0,
        "window_start": "2026-09-01",
        "window_end": "2026-10-01",
    }
    fallback_game = {
        "home": "Test Home",
        "away": "Test Away",
        "home_record_pct": 0.75,
        "away_record_pct": 0.25,
    }
    form = backend._recent_form_prediction(
        "NFL",
        fallback_game,
        backend.date_cls(2026, 10, 2),
        snapshot,
    )
    assert form is not None
    assert form["source"] == "keyless_recent_form_heuristic"
    assert form["home_win_probability"] > 0.5
    assert form["projected_score"]["home"] > form["projected_score"]["away"]

    empty_market = {
        "home_probability": None,
        "away_probability": None,
        "home_spread": -3.0,
        "away_spread": 3.0,
        "spread_pick": None,
        "spread_pick_probability": None,
        "total": 44.5,
        "total_pick": None,
        "total_pick_probability": None,
    }
    generated = backend._prediction_bundle(
        fallback_game,
        empty_market,
        form["projected_score"],
        form["home_win_probability"],
        form["source"],
        form["note"],
        form,
    )
    assert generated["generated"] is True
    assert generated["moneyline"]["pick"] == "Test Home"
    assert generated["spread"]["pick"] in {"Test Home", "Test Away"}
    assert generated["total"]["pick"] in {"OVER", "UNDER"}

    original_board_for_date = backend._board_for_date
    try:
        def fake_board(_date):
            game_candidates = []
            prop_candidates = []
            for sport_index, sport in enumerate(backend.SPORTS):
                for index in range(4):
                    common = {
                        "sport": sport,
                        "event_id": f"{sport}-event-{index}",
                        "event_time": f"2026-10-02T{12 + index:02d}:00:00Z",
                        "matchup": f"{sport} Away {index} @ {sport} Home {index}",
                        "best_available_book": "fixture_book",
                        "best_available_price": -110 + index,
                        "as_of": "2026-10-02T08:00:00Z",
                        "reason": "Fixture carries explicit fresh-market evidence for contract testing.",
                    }
                    game_candidates.append({
                        **common,
                        "type": "moneyline",
                        "label": f"{sport} GAME PICK {index}",
                        "probability": 0.72 - (sport_index * 0.01) - (index * 0.01),
                    })
                    prop_candidates.append({
                        **common,
                        "event_id": f"{sport}-prop-event-{index}",
                        "type": "player_prop",
                        "label": f"{sport} PLAYER PROP {index}",
                        "probability": 0.71 - (sport_index * 0.01) - (index * 0.01),
                    })
            return {
                "game_candidates": game_candidates,
                "prop_candidates": prop_candidates,
            }

        backend._board_for_date = fake_board
        best3 = backend._best_three_leg_parlays("2026-10-02")
        assert best3["parlays_per_sport"] == 2
        assert best3["legs_per_parlay"] == 3
        assert len(best3["cards"]) == 8
        for sport in backend.SPORTS:
            cards = [card for card in best3["cards"] if card["sport"] == sport]
            assert [card["rank"] for card in cards] == [1, 2]
            assert all(card["status"] == "OK" for card in cards)
            assert all(len(card["legs"]) == 3 for card in cards)
            assert all(card["reasoning"] for card in cards)
    finally:
        backend._board_for_date = original_board_for_date

    print("PhilthySports backend selftest PASS")


if __name__ == "__main__":
    main()
