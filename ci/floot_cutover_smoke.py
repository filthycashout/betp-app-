#!/usr/bin/env python3
"""Fail-closed production contract smoke for the PhilthyParleys Floot cutover.

This intentionally requires every mobile/dashboard contract needed for cutover.
It never treats a healthy /health route as sufficient release evidence.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://philthyparleys.floot.app/_api"
OUTPUT = Path("floot-cutover-report.json")


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


def main() -> int:
    checks: dict[str, dict[str, object]] = {}
    failures: list[str] = []

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
            and payload.get("service") == "philthysports-runtime",
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
            and payload.get("models", {}).get("marketBaselineFallback") is True,
            payload if isinstance(payload, dict) else type(payload).__name__,
        ),
    )

    check(
        "provider_canary",
        "/v1/providers/canary",
        lambda status, payload: (
            status == 200
            and isinstance(payload, dict)
            and payload.get("credentialledLiveProviderVerified") is True,
            payload if isinstance(payload, dict) else type(payload).__name__,
        ),
    )

    for sport in ("NFL", "NBA"):
        check(
            f"search_{sport.lower()}",
            f"/v1/search?sport={sport}",
            lambda status, payload, sport=sport: (
                status == 200
                and isinstance(payload, dict)
                and isinstance(payload.get("games"), list)
                and len(payload["games"]) > 0
                and all(row.get("sport") == sport for row in payload["games"][:5] if isinstance(row, dict)),
                {"games": len(payload.get("games", []))} if isinstance(payload, dict) else type(payload).__name__,
            ),
        )

    # These routes are the minimum dashboard/mobile cutover surface. Missing any
    # one keeps the candidate fail-closed on Render rollback rather than silently
    # promoting a partially functional backend.
    contract_paths = {
        "models_status": "/v1/models/status",
        "models_registry": "/v1/models/registry",
        "prop_capabilities": "/v1/system/props",
        "data_providers": "/v1/data/providers",
        "evidence_signals": "/v1/evidence/signals?limit=1",
        "best12": "/v1/picks/best12",
        "best3": "/v1/parlays/best3",
        "parlay7": "/v1/parlays/multisport?legs=7",
    }
    for name, path in contract_paths.items():
        check(
            name,
            path,
            lambda status, payload: (
                status == 200 and isinstance(payload, dict),
                payload if isinstance(payload, dict) else type(payload).__name__,
            ),
        )

    # A real event proves the fixed Floot detail route, not just collection APIs.
    try:
        _, search = get("/v1/search?sport=NFL")
        event_id = search.get("games", [{}])[0].get("event_id") if isinstance(search, dict) else None
    except Exception:
        event_id = None
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
    else:
        failures.append("game_detail")
        checks["game_detail"] = {"ok": False, "http_status": None, "detail": "No NFL event id available from candidate search"}

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
