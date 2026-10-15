from __future__ import annotations

import sports_web_research as research


def test_unconfigured_web_research_fails_closed(monkeypatch):
    monkeypatch.delenv("SGAI_API_KEY", raising=False)
    result = research.research_event(
        "NBA",
        "Home Team",
        "Away Team",
        event_time="2026-12-01T03:00:00Z",
        topic="availability",
    )
    assert result["status"] == "SCRAPEGRAPH_UNCONFIGURED"
    assert result["used_in_prediction"] is False
    assert result["historical_training_eligible"] is False
    assert result["trusted_for_instructions"] is False
    assert result["model_influence"] is False


def test_every_sport_has_availability_and_role_research_templates():
    for sport in ("NFL", "NBA", "MLB", "NHL"):
        assert set(research.TOPIC_PROMPTS[sport]) == {"availability", "roles"}


def test_invalid_topic_is_rejected():
    try:
        research.research_event("NFL", "Home", "Away", topic="betting_override")
    except ValueError as exc:
        assert "unsupported NFL research topic" in str(exc)
    else:
        raise AssertionError("invalid topic must fail closed")
