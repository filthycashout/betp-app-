from public_api_registry import REQUIRED_PROMOTION_EVIDENCE, promotion_decision, registry


def test_public_api_directory_is_discovery_only():
    payload = registry()
    assert payload["policy"] == "DISCOVERY_ONLY_FAIL_CLOSED"
    assert payload["production_candidates"] == []
    assert payload["candidates"]
    assert all(item["state"] == "DISCOVERED" for item in payload["candidates"])
    assert all(item["production_enabled"] is False for item in payload["candidates"])


def test_candidate_cannot_promote_with_partial_evidence():
    result = promotion_decision("nba-stats-publicapis", {"schema_validated": True})
    assert result["eligible"] is False
    assert result["state"] == "DISCOVERED"
    assert "live_canary_passed" in result["missing"]
    assert "immutable_raw_capture_sha256" in result["missing"]


def test_candidate_becomes_eligible_only_when_every_gate_passes():
    evidence = {key: True for key in REQUIRED_PROMOTION_EVIDENCE}
    result = promotion_decision("isports-publicapis", evidence)
    assert result["eligible"] is True
    assert result["state"] == "PRODUCTION_ELIGIBLE"
    assert result["missing"] == []


def test_unknown_candidate_fails_closed():
    result = promotion_decision("not-registered", {})
    assert result == {
        "candidate_id": "not-registered",
        "state": "REJECTED",
        "eligible": False,
        "missing": ["known_candidate"],
    }
