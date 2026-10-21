from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sports_ai.ingestion.ufc import UFC_ODDS_URL, normalize_ufc_events, fetch_ufc_events
from sports_ai.config.settings import Settings
from sports_ai.live import run_live_sport
from sports_ai.orchestrator import SportsAIEngine

PACIFIC = ZoneInfo("America/Los_Angeles")
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def event(*, event_id="ufc-1", start=None, sport_key="mma_mixed_martial_arts", home="Fighter A", away="Fighter B"):
    return {
        "id": event_id,
        "sport_key": sport_key,
        "sport_title": "MMA",
        "commence_time": (start or NOW + timedelta(hours=4)).isoformat().replace("+00:00", "Z"),
        "home_team": home,
        "away_team": away,
        "bookmakers": [{
            "key": "test-book",
            "title": "Test Book",
            "last_update": (NOW - timedelta(seconds=20)).isoformat().replace("+00:00", "Z"),
            "markets": [{
                "key": "h2h",
                "last_update": (NOW - timedelta(seconds=20)).isoformat().replace("+00:00", "Z"),
                "outcomes": [
                    {"name": home, "price": 110},
                    {"name": away, "price": -130},
                ],
            }],
        }],
    }


def test_normalizes_upcoming_fight_winner_event_without_inventing_props():
    target = (NOW + timedelta(hours=4)).astimezone(PACIFIC).date()
    rows = normalize_ufc_events([event()], target_date=target, now=NOW)
    assert len(rows) == 1
    row = rows[0]
    assert row["sport"] == "UFC"
    assert row["event_id"] == "ufc-1"
    assert row["home"] == "Fighter A"
    assert row["away"] == "Fighter B"
    assert row["market_scope"] == "fight_winner_moneyline"
    assert row["player_props_supported"] is False
    assert row["bookmakers"][0]["markets"][0]["key"] == "h2h"


def test_rejects_malformed_duplicate_past_and_wrong_sport_events():
    target = (NOW + timedelta(hours=4)).astimezone(PACIFIC).date()
    rows = normalize_ufc_events([
        event(event_id="past", start=NOW - timedelta(minutes=1)),
        event(event_id="wrong", sport_key="basketball_nba"),
        event(event_id="same", home="Fighter A", away="fighter a"),
        {"id": "missing-fighters", "commence_time": (NOW + timedelta(hours=4)).isoformat()},
        event(event_id="ok"),
        event(event_id="ok"),
    ], target_date=target, now=NOW)
    assert [row["event_id"] for row in rows] == ["ok"]


def test_requires_list_payload_and_can_return_empty_slate():
    assert normalize_ufc_events({"events": [event()]}, now=NOW) == []
    assert normalize_ufc_events([event(start=NOW - timedelta(seconds=1))], now=NOW) == []


def test_fetch_uses_rotated_credential_gate_and_expected_endpoint():
    target = (NOW + timedelta(hours=4)).astimezone(PACIFIC).date()
    calls = []
    runtime = SimpleNamespace(
        _odds_key=lambda: "rotated-test-key",
        _json=lambda url, *, params, timeout: calls.append((url, params, timeout)) or [event()],
    )
    rows = fetch_ufc_events(runtime, target, now=NOW)
    assert len(rows) == 1
    assert calls[0][0] == UFC_ODDS_URL
    assert calls[0][1]["markets"] == "h2h"
    assert calls[0][1]["regions"] == "us"
    assert calls[0][1]["apiKey"] == "rotated-test-key"
    assert calls[0][2] == 10


def test_fetch_propagates_missing_or_unrotated_credential_block():
    runtime = SimpleNamespace(_odds_key=lambda: (_ for _ in ()).throw(RuntimeError("credential unavailable")))
    target = (NOW + timedelta(hours=4)).astimezone(PACIFIC).date()
    try:
        fetch_ufc_events(runtime, target, now=NOW)
    except RuntimeError as exc:
        assert str(exc) == "credential unavailable"
    else:
        raise AssertionError("UFC fetch must fail closed without a rotated credential")



def test_live_ufc_is_non_actionable_without_verified_independent_sharp_anchor():
    from datetime import date

    start = NOW + timedelta(hours=6)
    target = start.astimezone(PACIFIC).date()
    runtime = SimpleNamespace(
        _odds_key=lambda: "rotated-test-key",
        _json=lambda url, *, params, timeout: [event(start=start)],
    )
    engine = SportsAIEngine(Settings(
        min_edge=0.03,
        min_market_quality=0.75,
        max_snapshot_age_seconds=900,
        market_weight=0.70,
        kelly_fraction=0.25,
        sharp_book_keys=("pinnacle",),
        sharp_max_age_seconds=180,
    ))

    result = run_live_sport(
        "UFC",
        date=target.isoformat(),
        backend=runtime,
        engine=engine,
    )

    assert result["status"] == "OK"
    assert result["execution_policy"]["automatic_wagering"] is False
    assert result["execution_policy"]["verified_sharp_anchor_required"] is True
    assert result["execution_policy"]["player_props_supported"] is False
    decision = result["decisions"][0]["decision"]["decision"]
    assert decision["eligible"] is False
    assert "SHARP_ANCHOR_UNVERIFIED" in decision["reasons"]
