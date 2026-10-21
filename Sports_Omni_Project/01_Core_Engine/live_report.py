"""Read-only Sports Omni reporting adapter for the existing governed backend.

This module never fetches prices directly, promotes a model, places bets, or
substitutes assumed prop/parlay prices. All decision gates remain in sports_ai.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

SUPPORTED_REPORT_SPORTS = ("NFL", "NBA", "MLB", "NHL", "UFC")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent


def _backend_runner() -> Callable[..., dict[str, Any]]:
    backend_root = str(REPO_ROOT / "backend")
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)
    from sports_ai.live import run_live_sport

    return run_live_sport


def _summarize_decision(sport: str, row: dict[str, Any]) -> dict[str, Any]:
    evaluated = row.get("decision")
    market = evaluated if isinstance(evaluated, dict) else {}
    details = market.get("decision")
    policy = details if isinstance(details, dict) else {}
    sharp = row.get("sharp_anchor")
    sharp_verified = (
        isinstance(sharp, dict)
        and sharp.get("verified") is True
        and market.get("sharp_anchor_verified") is True
    )
    model_verified = (
        row.get("promoted_model_contributed") is True
        and row.get("promotion_gate_passed") is True
        and market.get("model_promotion_passed") is True
    )
    eligible = policy.get("eligible") is True and sharp_verified
    # An eligible market baseline is not evidence of a trained-model prediction.
    category = (
        "MODEL_BACKED_ANALYSIS"
        if eligible and model_verified
        else "MARKET_ONLY_ANALYSIS"
        if eligible
        else "BLOCKED"
    )
    reasons = list(policy.get("reasons") or []) if isinstance(policy.get("reasons"), (tuple, list)) else []
    if not sharp_verified and "SHARP_ANCHOR_UNVERIFIED" not in reasons:
        reasons.append("SHARP_ANCHOR_UNVERIFIED")
    if row.get("status") != "EVALUATED":
        reasons.append(str(row.get("status") or "UNEVALUATED"))
    return {
        "sport": sport,
        "event_id": row.get("event_id"),
        "matchup": row.get("matchup"),
        "event_time": row.get("event_time"),
        "category": category,
        "selection": market.get("selection") if eligible else None,
        "market": market.get("market") if eligible else None,
        "american_odds": market.get("soft_american_odds") if eligible else None,
        "estimated_probability": market.get("final_probability") if eligible else None,
        "probability_source": market.get("probability_source") if eligible else None,
        "market_source": row.get("market_source"),
        "verified_sharp_anchor": sharp_verified,
        "promoted_model_contributed": model_verified,
        "reasons": sorted(set(reasons)),
        "manual_review_required": True,
    }


def summarize_live_results(
    results: dict[str, dict[str, Any]],
    *,
    report_date: str,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Project backend output into explicit, provenance-aware report categories."""
    date.fromisoformat(report_date)
    games: list[dict[str, Any]] = []
    sources: dict[str, str] = {}
    provider_failures: list[str] = []
    for sport, result in results.items():
        if sport not in SUPPORTED_REPORT_SPORTS:
            raise ValueError(f"unsupported sport: {sport}")
        if not isinstance(result, dict):
            raise ValueError("backend sport result must be an object")
        status = str(result.get("status") or "UNKNOWN")
        sources[sport] = status
        if status == "PROVIDER_UNAVAILABLE":
            provider_failures.append(sport)
        for row in result.get("decisions") or []:
            if isinstance(row, dict):
                games.append(_summarize_decision(sport, row))

    model_backed = [row for row in games if row["category"] == "MODEL_BACKED_ANALYSIS"]
    market_only = [row for row in games if row["category"] == "MARKET_ONLY_ANALYSIS"]
    blocked = [row for row in games if row["category"] == "BLOCKED"]
    status = (
        "PARTIAL_PROVIDER_FAILURE" if provider_failures
        else "MODEL_BACKED_ANALYSIS_AVAILABLE" if model_backed
        else "MARKET_ONLY_ANALYSIS_AVAILABLE" if market_only
        else "NO_VERIFIED_SELECTIONS"
    )
    return {
        "schema_version": "sports-omni-live-report-v1",
        "report_date": report_date,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "status": status,
        "sports": sources,
        "provider_failures": provider_failures,
        "counts": {
            "evaluated_rows": len(games),
            "model_backed": len(model_backed),
            "market_only": len(market_only),
            "blocked": len(blocked),
        },
        "model_backed_analyses": model_backed,
        "market_only_analyses": market_only,
        "blocked": blocked,
        "not_implemented_in_this_report": [
            "player_props",
            "dependence_aware_parlays",
            "automated_wagering",
        ],
        "execution_policy": {
            "automatic_wagering": False,
            "human_review_required": True,
            "unverified_predictions_suppressed": True,
        },
    }


def generate_live_report(
    *,
    report_date: str,
    sports: tuple[str, ...] = SUPPORTED_REPORT_SPORTS,
    runner: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    date.fromisoformat(report_date)
    live_runner = runner or _backend_runner()
    results: dict[str, dict[str, Any]] = {}
    for sport in dict.fromkeys(sports):
        if sport not in SUPPORTED_REPORT_SPORTS:
            raise ValueError(f"unsupported sport: {sport}")
        try:
            result = live_runner(sport, date=report_date)
            if not isinstance(result, dict):
                raise TypeError("live backend returned non-object")
            results[sport] = result
        except Exception as exc:
            # The exception class is useful for operators; exception text can
            # contain credentials, URLs, or response bodies, and is not emitted.
            results[sport] = {
                "status": "PROVIDER_UNAVAILABLE",
                "error_type": type(exc).__name__,
                "decisions": [],
            }
    return summarize_live_results(results, report_date=report_date)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a read-only Sports Omni live report from the existing backend")
    parser.add_argument("--date", help="Event date in YYYY-MM-DD (default: Pacific today)")
    parser.add_argument("--sport", action="append", choices=SUPPORTED_REPORT_SPORTS, help="Repeat to select sports")
    parser.add_argument("--output", type=Path, help="Report path (default: dated games output)")
    args = parser.parse_args()
    report_date = args.date or datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    try:
        report = generate_live_report(report_date=report_date, sports=tuple(args.sport or SUPPORTED_REPORT_SPORTS))
    except ValueError as exc:
        parser.error(str(exc))
    path = args.output or PROJECT_ROOT / "05_Daily_Outputs" / "games" / f"{report_date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(path), "status": report["status"], "counts": report["counts"]}, sort_keys=True))
    return 2 if report["provider_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
