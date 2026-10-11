#!/usr/bin/env python3
"""Fail-closed production contract smoke for the PhilthyParleys Floot cutover.

This intentionally requires the mobile/dashboard contracts needed for cutover,
plus fresh four-sport Powerhouse evidence. A healthy /health route or a 200-only
shape check is not sufficient release evidence.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://philthyparleys.floot.app/_api"
OUTPUT = Path("floot-cutover-report.json")
SPORTS = ("NFL", "NBA", "MLB", "NHL")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def unwrap_floot(payload: object) -> object:
    if isinstance(payload, dict) and isinstance(payload.get("json"), dict):
        return payload["json"]
    return payload


def get(path: str, timeout: int = 30) -> tuple[int, object]:
    url = BASE + path
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "PhilthyParleys/floot-cutover-guard"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read(5_000_001)
            if len(body) > 5_000_000:
                raise RuntimeError(f"response too large for {path}")
            return response.status, unwrap_floot(json.loads(body.decode("utf-8")))
    except urllib.error.HTTPError as exc:
        body = exc.read(200_000).decode("utf-8", errors="replace")
        try:
            parsed: object = unwrap_floot(json.loads(body))
        except Exception:
            parsed = {"raw": body[:2000]}
        return exc.code, parsed


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


def valid_evidence(row: object) -> bool:
    if not isinstance(row, dict):
        return False
    return (
        row.get("status") == "RECORDED"
        and isinstance(row.get("signal_id"), str)
        and bool(row.get("signal_id"))
        and isinstance(row.get("record_sha256"), str)
        and bool(SHA256_RE.fullmatch(row["record_sha256"]))
        and isinstance(row.get("engine_version"), str)
        and row["engine_version"].startswith("floot-powerhouse-runtime-")
    )


def valid_live_selection(row: object, *, require_sport: str | None = None) -> bool:
    if not isinstance(row, dict):
        return False
    if require_sport is not None and row.get("sport") != require_sport:
        return False
    event_time = parse_utc(row.get("event_time"))
    if event_time is None or event_time <= datetime.now(timezone.utc):
        return False
    market = row.get("market")
    if not isinstance(market, dict):
        return False
    if market.get("freshness_verified") is not True or market.get("provider_timestamp_verified") is not True:
        return False
    if parse_utc(market.get("observed_at")) is None:
        return False
    return valid_evidence(row.get("evidence"))


def main() -> int:
    checks: dict[str, dict[str, object]] = {}
    failures: list[str] = []
    search_payloads: dict[str, dict[str, object]] = {}

    def check(name: str, path: str, validator) -> object | None:
        try:
            status, payload = get(path)
            ok, detail = validator(status, payload)
            checks[name] = {"ok": ok, "http_status": status, "detail": detail}
            if not ok:
                failures.append(name)
            return payload
        except Exception as exc:  # network/DNS/JSON failures are release blockers
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
        payload = check(
            f"search_{sport.lower()}",
            f"/v1/search?sport={sport}",
            lambda status, payload, sport=sport: (
                status == 200
                and isinstance(payload, dict)
                and isinstance(payload.get("games"), list)
                and len(payload["games"]) > 0
                and all(valid_live_selection(row, require_sport=sport) for row in payload["games"]),
                {
                    "games": len(payload.get("games", [])),
                    "all_future_and_fresh": (
                        all(valid_live_selection(row, require_sport=sport) for row in payload.get("games", []))
                        if isinstance(payload, dict) and isinstance(payload.get("games"), list)
                        else False
                    ),
                }
                if isinstance(payload, dict)
                else type(payload).__name__,
            ),
        )
        if isinstance(payload, dict):
            search_payloads[sport] = payload

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
            and all(isinstance(payload["sports"].get(sport), list) and len(payload["sports"][sport]) > 0 for sport in SPORTS)
            and isinstance(payload.get("default_live_markets"), dict)
            and all(isinstance(payload["default_live_markets"].get(sport), list) and len(payload["default_live_markets"][sport]) > 0 for sport in SPORTS),
            payload if isinstance(payload, dict) else type(payload).__name__,
        ),
    )

    for name, path in {
        "data_providers": "/v1/data/providers",
        "evidence_signals": "/v1/evidence/signals?limit=1",
        "best3": "/v1/parlays/best3",
    }.items():
        check(
            name,
            path,
            lambda status, payload: (
                status == 200 and isinstance(payload, dict),
                payload if isinstance(payload, dict) else type(payload).__name__,
            ),
        )

    check(
        "best12",
        "/v1/picks/best12",
        lambda status, payload: (
            status == 200
            and isinstance(payload, dict)
            and payload.get("requested") == 12
            and isinstance(payload.get("picks"), list)
            and len(payload["picks"]) == 12
            and all(valid_live_selection(row) for row in payload["picks"]),
            {
                "picks": len(payload.get("picks", [])),
                "all_future_and_fresh": (
                    all(valid_live_selection(row) for row in payload.get("picks", []))
                    if isinstance(payload, dict) and isinstance(payload.get("picks"), list)
                    else False
                ),
                "probability_source": payload.get("probability_source") if isinstance(payload, dict) else None,
            }
            if isinstance(payload, dict)
            else type(payload).__name__,
        ),
    )

    for legs in (7, 10, 14):
        check(
            f"parlay{legs}",
            f"/v1/parlays/multisport?legs={legs}",
            lambda status, payload, legs=legs: (
                status == 200
                and isinstance(payload, dict)
                and payload.get("requested_legs") == legs
                and payload.get("complete") is True
                and isinstance(payload.get("legs"), list)
                and len(payload["legs"]) == legs
                and all(valid_live_selection(row) for row in payload["legs"])
                and payload.get("manual_review_only") is True
                and payload.get("joint_probability") is None
                and payload.get("dependence_model") == "UNAVAILABLE",
                {
                    "requested": legs,
                    "returned": len(payload.get("legs", [])),
                    "complete": payload.get("complete"),
                    "all_future_and_fresh": (
                        all(valid_live_selection(row) for row in payload.get("legs", []))
                        if isinstance(payload, dict) and isinstance(payload.get("legs"), list)
                        else False
                    ),
                    "joint_probability": payload.get("joint_probability"),
                    "dependence_model": payload.get("dependence_model"),
                }
                if isinstance(payload, dict)
                else type(payload).__name__,
            ),
        )

    # A real future NFL event proves the fixed Floot detail route, not just collections.
    nfl_games = search_payloads.get("NFL", {}).get("games", [])
    first_nfl = nfl_games[0] if isinstance(nfl_games, list) and nfl_games else None
    event_id = first_nfl.get("event_id") if isinstance(first_nfl, dict) else None
    if isinstance(event_id, str) and event_id:
        query = urllib.parse.urlencode({"sport": "NFL", "event_id": event_id})
        check(
            "game_detail",
            f"/v1/game?{query}",
            lambda status, payload: (
                status == 200 and isinstance(payload, dict),
                payload if isinstance(payload, dict) else type(payload).__name__,
            ),
        )

        evidence = first_nfl.get("evidence") if isinstance(first_nfl, dict) else None
        signal_id = evidence.get("signal_id") if isinstance(evidence, dict) else None
        expected_sha = evidence.get("record_sha256") if isinstance(evidence, dict) else None
        if isinstance(signal_id, str) and signal_id:
            verify_query = urllib.parse.urlencode({"signal": signal_id})
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
            checks["evidence_verify"] = {"ok": False, "http_status": None, "detail": "No evidence signal on fresh NFL event"}
    else:
        failures.append("game_detail")
        checks["game_detail"] = {"ok": False, "http_status": None, "detail": "No fresh NFL event id available from candidate search"}

    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "base_url": BASE,
        "passed": not failures,
        "failed_checks": sorted(set(failures)),
        "checks": checks,
    }
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
