#!/usr/bin/env python3
"""Fail-closed production contract smoke for the PhilthyParleys Floot cutover.

This verifies the deployed service contract without assuming that a current
slate must contain games or qualifying recommendations. Production-contract
checks are deliberately provider-quota-safe: live-data routes are probed with
``refresh=false`` and durable evidence is verified independently.
"""
from __future__ import annotations

import json
import math
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

BASE = "https://philthyparleys.floot.app/_api"
OUTPUT = Path("floot-cutover-report.json")
SPORTS = ("NFL", "NBA", "MLB", "NHL")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
STRICT_RECOMMENDATION_GATE = "verified_sharp_vs_independent_soft_ev"


def unwrap_floot(payload: object) -> object:
    if isinstance(payload, dict) and isinstance(payload.get("json"), dict):
        return payload["json"]
    return payload


def get(path: str, timeout: int = 30) -> tuple[int, object]:
    request = urllib.request.Request(
        BASE + path,
        headers={"Accept": "application/json", "User-Agent": "PhilthyParleys/floot-cutover-guard"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(5_000_001)
            if len(body) > 5_000_000:
                raise RuntimeError(f"response too large for {path}")
            return response.status, unwrap_floot(json.loads(body.decode("utf-8")))
    except urllib.error.HTTPError as exc:
        body = exc.read(200_000).decode("utf-8", errors="replace")
        try:
            payload: object = unwrap_floot(json.loads(body))
        except Exception:
            payload = {"raw": body[:2000]}
        return exc.code, payload


def parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def finite_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def valid_evidence(row: object) -> bool:
    return bool(
        isinstance(row, dict)
        and row.get("status") == "RECORDED"
        and isinstance(row.get("signal_id"), str)
        and row.get("signal_id")
        and isinstance(row.get("record_sha256"), str)
        and SHA256_RE.fullmatch(row["record_sha256"])
        and isinstance(row.get("engine_version"), str)
        and row["engine_version"].startswith("floot-powerhouse-runtime-")
    )


def valid_live_selection(row: object, *, require_sport: str | None = None) -> bool:
    if not isinstance(row, dict):
        return False
    if require_sport is not None and row.get("sport") != require_sport:
        return False
    event_time = parse_utc(row.get("event_time"))
    market = row.get("market")
    return bool(
        event_time is not None
        and event_time > datetime.now(timezone.utc)
        and isinstance(market, dict)
        and market.get("freshness_verified") is True
        and market.get("provider_timestamp_verified") is True
        and parse_utc(market.get("observed_at")) is not None
        and valid_evidence(row.get("evidence"))
    )


def valid_ranked_pick(row: object) -> bool:
    if not valid_live_selection(row) or not isinstance(row, dict):
        return False
    probability = finite_number(row.get("probability"))
    edge = finite_number(row.get("edge"))
    expected_value = finite_number(row.get("expected_value"))
    offered_american = finite_number(row.get("offered_american"))
    return bool(
        isinstance(row.get("selection"), str)
        and row.get("selection")
        and probability is not None
        and 0.0 < probability < 1.0
        and edge is not None
        and edge >= 0.03
        and expected_value is not None
        and expected_value > 0.0
        and row.get("sharp_anchor_verified") is True
        and offered_american is not None
        and offered_american != 0.0
        and abs(offered_american) >= 100.0
        and isinstance(row.get("offered_book"), str)
        and row.get("offered_book")
    )


def validate_best12(status: int, payload: object) -> tuple[bool, object]:
    if not isinstance(payload, dict):
        return False, type(payload).__name__
    picks = payload.get("picks")
    ok = bool(
        status == 200
        and payload.get("requested") == 12
        and payload.get("recommendation_gate") == STRICT_RECOMMENDATION_GATE
        and isinstance(picks, list)
        and len(picks) <= 12
        and all(valid_ranked_pick(row) for row in picks)
    )
    return ok, {
        "requested": payload.get("requested"),
        "picks": len(picks) if isinstance(picks, list) else None,
        "all_returned_picks_strictly_eligible": all(valid_ranked_pick(row) for row in picks) if isinstance(picks, list) else False,
        "empty_slate_allowed": True,
        "recommendation_gate": payload.get("recommendation_gate"),
        "probability_source": payload.get("probability_source"),
    }


def validate_best3(status: int, payload: object) -> tuple[bool, object]:
    if not isinstance(payload, dict):
        return False, type(payload).__name__
    legs = payload.get("legs")
    ok = bool(
        status == 200
        and payload.get("requested") == 3
        and payload.get("recommendation_gate") == STRICT_RECOMMENDATION_GATE
        and isinstance(legs, list)
        and len(legs) <= 3
        and all(valid_ranked_pick(row) for row in legs)
        and payload.get("joint_probability") is None
        and payload.get("dependence_model") == "UNAVAILABLE"
    )
    return ok, {
        "requested": payload.get("requested"),
        "returned": len(legs) if isinstance(legs, list) else None,
        "all_returned_legs_strictly_eligible": all(valid_ranked_pick(row) for row in legs) if isinstance(legs, list) else False,
        "joint_probability": payload.get("joint_probability"),
        "dependence_model": payload.get("dependence_model"),
        "recommendation_gate": payload.get("recommendation_gate"),
    }


def validate_parlay(status: int, payload: object, requested: int) -> tuple[bool, object]:
    if not isinstance(payload, dict) or not isinstance(payload.get("legs"), list):
        return False, type(payload).__name__
    legs = payload["legs"]
    complete = len(legs) == requested
    expected_status = "SHARP_VERIFIED_EV_CARD" if complete else "INSUFFICIENT_ELIGIBLE_LIVE_EVENTS"
    ok = bool(
        status == 200
        and payload.get("requested_legs") == requested
        and payload.get("recommendation_gate") == STRICT_RECOMMENDATION_GATE
        and payload.get("complete") == complete
        and len(legs) <= requested
        and all(valid_ranked_pick(row) for row in legs)
        and payload.get("manual_review_only") is True
        and payload.get("joint_probability") is None
        and payload.get("dependence_model") == "UNAVAILABLE"
        and payload.get("status") == expected_status
    )
    return ok, {
        "requested": requested,
        "returned": len(legs),
        "complete": payload.get("complete"),
        "status": payload.get("status"),
        "expected_status": expected_status,
        "all_returned_legs_strictly_eligible": all(valid_ranked_pick(row) for row in legs),
        "empty_or_partial_slate_allowed": not complete,
        "joint_probability": payload.get("joint_probability"),
        "dependence_model": payload.get("dependence_model"),
        "recommendation_gate": payload.get("recommendation_gate"),
    }


def main() -> int:
    checks: dict[str, dict[str, object]] = {}
    failures: list[str] = []
    payloads: dict[str, object] = {}

    def check(name: str, path: str, validator: Callable[[int, object], tuple[bool, object]]) -> object | None:
        try:
            status, payload = get(path)
            ok, detail = validator(status, payload)
            checks[name] = {"ok": ok, "http_status": status, "detail": detail}
            if not ok:
                failures.append(name)
            payloads[name] = payload
            return payload
        except Exception as exc:
            checks[name] = {"ok": False, "http_status": None, "detail": f"{type(exc).__name__}: {exc}"}
            failures.append(name)
            return None

    check(
        "health",
        "/health",
        lambda status, payload: (
            status == 200
            and isinstance(payload, dict)
            and payload.get("status") == "ok"
            and payload.get("service") == "philthysports-runtime"
            and payload.get("host") == "Floot",
            payload if isinstance(payload, dict) else type(payload).__name__,
        ),
    )

    check(
        "system_status",
        "/v1/system/status",
        lambda status, payload: (
            status == 200
            and isinstance(payload, dict)
            and payload.get("database", {}).get("durable") is True
            and payload.get("database", {}).get("configured") is True
            and payload.get("manual_review_only") is True
            and payload.get("models", {}).get("marketBaselineFallback") is True
            and all(int(payload.get("evidence", {}).get(f"{sport.lower()}Rows", 0)) > 0 for sport in SPORTS),
            payload if isinstance(payload, dict) else type(payload).__name__,
        ),
    )

    check(
        "provider_canary",
        "/v1/providers/canary",
        lambda status, payload: (
            status == 200
            and isinstance(payload, dict)
            and payload.get("credentialledLiveProviderVerified") is True
            and isinstance(payload.get("theOddsApi"), dict)
            and payload["theOddsApi"].get("authenticated") is True
            and payload["theOddsApi"].get("schemaValid") is True
            and payload["theOddsApi"].get("httpStatus") == 200
            and all(payload["theOddsApi"].get(f"{sport.lower()}Visible") is True for sport in SPORTS),
            payload if isinstance(payload, dict) else type(payload).__name__,
        ),
    )

    for sport in SPORTS:
        check(
            f"search_{sport.lower()}",
            f"/v1/search?sport={sport}&include_props=false&refresh=false",
            lambda status, payload, sport=sport: (
                status == 200
                and isinstance(payload, dict)
                and isinstance(payload.get("games"), list)
                and all(valid_live_selection(row, require_sport=sport) for row in payload["games"]),
                {
                    "games": len(payload.get("games", [])),
                    "all_returned_games_future_and_fresh": all(valid_live_selection(row, require_sport=sport) for row in payload.get("games", [])),
                    "empty_slate_allowed": True,
                    "provider_refresh": False,
                }
                if isinstance(payload, dict) and isinstance(payload.get("games"), list)
                else type(payload).__name__,
            ),
        )

    check(
        "models_status",
        "/v1/models/status",
        lambda status, payload: (
            status == 200
            and isinstance(payload, dict)
            and payload.get("manual_review_only") is True
            and isinstance(payload.get("models"), dict)
            and all(isinstance(payload["models"].get(sport), dict) for sport in SPORTS)
            and (
                payload.get("market_baseline_only") is not True
                or all(
                    payload["models"][sport].get("runtime_mode") == "MARKET_BASELINE_ONLY"
                    and payload["models"][sport].get("promoted_artifact_loaded") is False
                    for sport in SPORTS
                )
            ),
            payload if isinstance(payload, dict) else type(payload).__name__,
        ),
    )

    check(
        "models_registry",
        "/v1/models/registry",
        lambda status, payload: (
            status == 200 and isinstance(payload, dict) and isinstance(payload.get("models"), list),
            payload if isinstance(payload, dict) else type(payload).__name__,
        ),
    )

    check(
        "prop_capabilities",
        "/v1/system/props",
        lambda status, payload: (
            status == 200
            and isinstance(payload, dict)
            and payload.get("live_props_supported") is True
            and payload.get("status") == "LIVE_EVENT_PROP_FEED_CONFIGURED"
            and payload.get("provider") == "the_odds_api_v4_event_odds"
            and isinstance(payload.get("sports"), dict)
            and all(isinstance(payload["sports"].get(sport), list) and payload["sports"][sport] for sport in SPORTS),
            payload if isinstance(payload, dict) else type(payload).__name__,
        ),
    )

    check(
        "data_providers",
        "/v1/data/providers",
        lambda status, payload: (
            status == 200 and isinstance(payload, dict),
            payload if isinstance(payload, dict) else type(payload).__name__,
        ),
    )
    evidence_signals = check(
        "evidence_signals",
        "/v1/evidence/signals?limit=1",
        lambda status, payload: (
            status == 200
            and isinstance(payload, dict)
            and payload.get("durable_storage") is True
            and isinstance(payload.get("signals"), list)
            and bool(payload["signals"]),
            payload if isinstance(payload, dict) else type(payload).__name__,
        ),
    )

    check("best3", "/v1/parlays/best3?refresh=false", validate_best3)
    check("best12", "/v1/picks/best12?refresh=false", validate_best12)
    for legs in (7, 10, 14):
        check(
            f"parlay{legs}",
            f"/v1/parlays/multisport?legs={legs}&refresh=false",
            lambda status, payload, legs=legs: validate_parlay(status, payload, legs),
        )

    sentinel_query = urllib.parse.urlencode(
        {"sport": "NFL", "event_id": "__philthy_contract_probe__", "refresh": "false"}
    )
    for name, path in {
        "game_detail": f"/v1/game?{sentinel_query}",
        "game_props": f"/v1/game/props?{sentinel_query}",
        "game_best9": f"/v1/game/best9?{sentinel_query}",
    }.items():
        check(
            name,
            path,
            lambda status, payload: (
                status == 404
                and isinstance(payload, dict)
                and payload.get("error") == "Game not found",
                {
                    "route_present": status == 404 and isinstance(payload, dict) and payload.get("error") == "Game not found",
                    "structured_domain_rejection": payload if isinstance(payload, dict) else type(payload).__name__,
                    "provider_refresh": False,
                },
            ),
        )

    latest_signal = None
    if isinstance(evidence_signals, dict) and isinstance(evidence_signals.get("signals"), list) and evidence_signals["signals"]:
        candidate = evidence_signals["signals"][0]
        if isinstance(candidate, dict):
            latest_signal = candidate
    if latest_signal and isinstance(latest_signal.get("signal_id"), str):
        expected_sha = latest_signal.get("record_sha256")
        verify_query = urllib.parse.urlencode({"signal": latest_signal["signal_id"]})
        check(
            "evidence_verify",
            f"/v1/evidence/verify?{verify_query}",
            lambda status, payload, expected_sha=expected_sha: (
                status == 200
                and isinstance(payload, dict)
                and payload.get("verified") is True
                and payload.get("immutable") is True
                and payload.get("record_sha256") == expected_sha,
                payload if isinstance(payload, dict) else type(payload).__name__,
            ),
        )
    else:
        failures.append("evidence_verify")
        checks["evidence_verify"] = {
            "ok": False,
            "http_status": None,
            "detail": "No durable evidence signal available to verify",
        }

    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "base_url": BASE,
        "passed": not failures,
        "failed_checks": sorted(set(failures)),
        "contract": {
            "recommendation_gate": STRICT_RECOMMENDATION_GATE,
            "empty_slate_policy": "valid_when_no_strictly_eligible_picks_or_current_events_exist",
            "route_probe_policy": "quota_safe_refresh_false_with_structured_sentinel_rejection",
            "evidence_policy": "verify_latest_durable_signal_independent_of_current_slate",
            "parlay_dependence_policy": "joint_probability_remains_null_while_dependence_model_unavailable",
        },
        "checks": checks,
    }
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
