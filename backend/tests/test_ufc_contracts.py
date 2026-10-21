from datetime import datetime, timezone

from sports.ufc.contracts import normalize_event, normalize_market, provider_status


NOW = datetime(2026, 10, 20, 20, 0, tzinfo=timezone.utc)
FETCHED = "2026-10-20T20:00:00Z"


def valid_event():
    return {
        "event_id": "mma-123",
        "fighter_a": "Fighter A",
        "fighter_b": "Fighter B",
        "start_time": "2026-10-22T01:00:00Z",
        "weight_class": "Lightweight",
        "scheduled_rounds": 3,
    }


def test_event_normalization_retains_provenance_and_is_not_promotion_eligible():
    result = normalize_event(
        valid_event(),
        provider="authorized-test-fixture",
        fetched_at=FETCHED,
        now=NOW,
    )
    assert result is not None
    assert result["sport"] == "UFC"
    assert result["source_event_id"] == "mma-123"
    assert result["provider"] == "authorized-test-fixture"
    assert result["promotion_eligible"] is False
    assert result["evidence_status"] == "NORMALIZED_UNVERIFIED_PROVIDER"


def test_event_rejects_missing_identity_or_same_fighter():
    assert normalize_event(
        {"fighter_a": "A", "fighter_b": "B", "start_time": "2026-10-22T01:00:00Z"},
        provider="fixture",
        fetched_at=FETCHED,
        now=NOW,
    ) is None
    bad = {**valid_event(), "fighter_b": "Fighter A"}
    assert normalize_event(bad, provider="fixture", fetched_at=FETCHED, now=NOW) is None


def test_event_rejects_naive_or_past_timestamps():
    naive = {**valid_event(), "start_time": "2026-10-22T01:00:00"}
    assert normalize_event(naive, provider="fixture", fetched_at=FETCHED, now=NOW) is None
    past = {**valid_event(), "start_time": "2026-10-19T01:00:00Z"}
    assert normalize_event(past, provider="fixture", fetched_at=FETCHED, now=NOW) is None


def test_market_requires_quote_timestamp_and_valid_price():
    valid = {
        "market_id": "fight_winner",
        "selection": "Fighter A",
        "american_price": -120,
        "quoted_at": FETCHED,
        "line": None,
    }
    result = normalize_market(
        valid,
        provider="authorized-test-fixture",
        source_event_id="mma-123",
        fetched_at=FETCHED,
    )
    assert result is not None
    assert result["american_price"] == -120
    assert result["promotion_eligible"] is False
    assert normalize_market(
        {**valid, "american_price": 0},
        provider="fixture",
        source_event_id="mma-123",
        fetched_at=FETCHED,
    ) is None
    assert normalize_market(
        {k: v for k, v in valid.items() if k != "quoted_at"},
        provider="fixture",
        source_event_id="mma-123",
        fetched_at=FETCHED,
    ) is None


def test_provider_is_unavailable_until_configured_and_canary_verified():
    assert provider_status()["status"] == "UNAVAILABLE"
    assert provider_status(configured=True)["status"] == "UNAVAILABLE"
    assert provider_status(configured=True, canary_verified=True)["status"] == "VERIFIED"
    assert provider_status(configured=True, canary_verified=True)["live_picks_enabled"] is False
