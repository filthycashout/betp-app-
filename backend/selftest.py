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
                    "total": 45.0,
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
