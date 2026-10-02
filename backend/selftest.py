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
        # Current checked-in bundle is the governed fallback, not promoted trained ML.
        assert gate["passed"] is False
        assert gate["runtime_role"] == "BASELINE_FALLBACK"

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
        gated = backend.props("MLB", "event", odds_event_id="provider-event")
        assert gated["status"] == "CONTRACT_READY_LIVE_KEY_REQUIRED"
        assert gated["props"] == []
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

    original_search = backend._search
    try:
        backend._search = lambda *args, **kwargs: _fake_games()
        p7 = backend._build_multisport_parlay(7, "2026-10-02")
        p10 = backend._build_multisport_parlay(10, "2026-10-02")
        p14 = backend._build_multisport_parlay(14, "2026-10-02")
        assert p7["actual_legs"] == 7 and p7["multisport"]
        assert p10["actual_legs"] == 10 and p10["multisport"]
        assert p14["actual_legs"] == 14 and p14["multisport"]
        assert p14["estimated_joint_probability"] is None
        assert p14["dependency_method"] == "UNSCORED_WITHOUT_VALIDATED_DEPENDENCY_MODEL"
        assert all(leg.get("reason") for leg in p14["legs"])
        assert {"moneyline", "spread", "total"}.issubset(
            {leg["type"] for leg in p14["legs"]}
        )
        assert p7["card_id"] != p10["card_id"] != p14["card_id"]
        assert p7["selection_profile"] != p10["selection_profile"]
        assert p10["selection_profile"] != p14["selection_profile"]
    finally:
        backend._search = original_search

    try:
        backend._build_multisport_parlay(3, "2026-10-02")
        raise AssertionError("invalid leg count did not fail")
    except ValueError:
        pass

    print("PhilthySports backend selftest PASS")


if __name__ == "__main__":
    main()
