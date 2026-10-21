from __future__ import annotations

from live_report import SUPPORTED_REPORT_SPORTS, generate_live_report, summarize_live_results


def _decision(*, eligible=True, promoted=False, sharp=True):
    return {
        "status": "EVALUATED",
        "event_id": "test-event",
        "matchup": "Away @ Home",
        "event_time": "2026-10-22T00:00:00+00:00",
        "market_source": "FIXTURE_ONLY",
        "sharp_anchor": {"verified": sharp},
        "promotion_gate_passed": promoted,
        "promoted_model_contributed": promoted,
        "decision": {
            "market": "moneyline",
            "selection": "Home",
            "soft_american_odds": 125.0,
            "final_probability": 0.60,
            "probability_source": "PROMOTED_MARKET_CONDITIONED_MODEL" if promoted else "MARKET_BASELINE",
            "sharp_anchor_verified": sharp,
            "model_promotion_passed": promoted,
            "decision": {"eligible": eligible, "reasons": [] if eligible else ["EDGE_BELOW_THRESHOLD"]},
        },
    }


def test_market_baseline_is_not_mislabeled_as_promoted_prediction():
    report = summarize_live_results(
        {"NFL": {"status": "OK", "decisions": [_decision(promoted=False)]}},
        report_date="2026-10-21",
        generated_at="2026-10-21T00:00:00Z",
    )
    assert report["counts"] == {"evaluated_rows": 1, "model_backed": 0, "market_only": 1, "blocked": 0}
    assert report["status"] == "MARKET_ONLY_ANALYSIS_AVAILABLE"
    assert report["execution_policy"]["automatic_wagering"] is False
    assert report["model_backed_analyses"] == []


def test_promoted_and_verified_selection_is_separately_labeled():
    report = summarize_live_results(
        {"NBA": {"status": "OK", "decisions": [_decision(promoted=True)]}},
        report_date="2026-10-21",
    )
    assert report["status"] == "MODEL_BACKED_ANALYSIS_AVAILABLE"
    assert report["model_backed_analyses"][0]["american_odds"] == 125.0
    assert report["model_backed_analyses"][0]["manual_review_required"] is True


def test_missing_sharp_anchor_blocks_selection_and_hides_price():
    report = summarize_live_results(
        {"NHL": {"status": "OK", "decisions": [_decision(promoted=True, sharp=False)]}},
        report_date="2026-10-21",
    )
    assert report["counts"]["blocked"] == 1
    blocked = report["blocked"][0]
    assert blocked["selection"] is None
    assert blocked["american_odds"] is None
    assert "SHARP_ANCHOR_UNVERIFIED" in blocked["reasons"]


def test_ineligible_decision_is_blocked_even_with_sharp_anchor():
    report = summarize_live_results(
        {"MLB": {"status": "OK", "decisions": [_decision(eligible=False)]}},
        report_date="2026-10-21",
    )
    assert report["status"] == "NO_VERIFIED_SELECTIONS"
    assert "EDGE_BELOW_THRESHOLD" in report["blocked"][0]["reasons"]


def test_provider_failure_keeps_other_sports_and_does_not_fabricate_picks():
    def backend(sport, *, date):
        if sport == "UFC":
            raise RuntimeError("secret-text-never-emit")
        return {"status": "NO_MATCHING_GAMES", "decisions": []}
    report = generate_live_report(report_date="2026-10-21", sports=("NFL", "UFC"), runner=backend)
    assert report["status"] == "PARTIAL_PROVIDER_FAILURE"
    assert report["sports"] == {"NFL": "NO_MATCHING_GAMES", "UFC": "PROVIDER_UNAVAILABLE"}
    assert report["counts"]["evaluated_rows"] == 0
    assert "secret-text-never-emit" not in str(report)


def test_default_sports_include_ufc_and_all_four_leagues():
    assert set(SUPPORTED_REPORT_SPORTS) == {"NFL", "NBA", "MLB", "NHL", "UFC"}
    called = []
    def backend(sport, *, date):
        called.append((sport, date))
        return {"status": "NO_MATCHING_GAMES", "decisions": []}
    report = generate_live_report(report_date="2026-10-21", runner=backend)
    assert len(called) == 5
    assert len(report["sports"]) == 5
