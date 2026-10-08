#!/usr/bin/env python3
"""Portable PhilthyParleys backend contract smoke.

Designed to run against the local Docker image in GitHub Actions or any deployed
host. It verifies that the canonical FastAPI backend exposes the full mobile
contract so deployment providers cannot silently ship a partial API surface.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REQUIRED_OPENAPI_PATHS = {
    "/health",
    "/v1/system/status",
    "/v1/models/status",
    "/v1/models/registry",
    "/v1/system/props",
    "/v1/data/providers",
    "/v1/evidence/signals",
    "/v1/search",
    "/v1/games/{sport}/{event_id}",
    "/v1/games/{sport}/{event_id}/props",
    "/v1/games/{sport}/{event_id}/best9",
    "/v1/picks/best12",
    "/v1/parlays/best3",
    "/v1/parlays/multisport",
}


def get_json(base: str, path: str, timeout: int = 35) -> tuple[int, Any]:
    url = base.rstrip("/") + path
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "PhilthyParleys/portable-contract"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read(5_000_000).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read(1_000_000).decode("utf-8", errors="replace")
        try:
            body: Any = json.loads(raw)
        except Exception:
            body = {"raw": raw[:2000]}
        return exc.code, body


def wait_for_health(base: str, seconds: int = 90) -> dict[str, Any]:
    deadline = time.monotonic() + seconds
    last: str = "no response"
    while time.monotonic() < deadline:
        try:
            status, body = get_json(base, "/health", timeout=5)
            if status == 200 and isinstance(body, dict) and body.get("status") == "ok":
                return body
            last = f"HTTP {status}: {body!r}"
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(2)
    raise RuntimeError(f"backend did not become healthy: {last}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8080")
    parser.add_argument("--report", type=Path, default=Path("portable-backend-contract.json"))
    args = parser.parse_args()

    failures: list[str] = []
    checks: dict[str, Any] = {}

    health = wait_for_health(args.base)
    checks["health"] = health
    if health.get("service") != "philthysports-runtime":
        failures.append("health.service")

    openapi_status, openapi = get_json(args.base, "/openapi.json")
    if openapi_status != 200 or not isinstance(openapi, dict):
        failures.append("openapi")
        paths: set[str] = set()
    else:
        paths = set((openapi.get("paths") or {}).keys())
        missing = sorted(REQUIRED_OPENAPI_PATHS - paths)
        checks["openapi_missing"] = missing
        if missing:
            failures.extend(f"route:{path}" for path in missing)

    static_checks = {
        "system_status": "/v1/system/status",
        "models_status": "/v1/models/status",
        "models_registry": "/v1/models/registry",
        "prop_capabilities": "/v1/system/props",
        "data_providers": "/v1/data/providers",
        "evidence_signals": "/v1/evidence/signals?limit=1",
        "search_nfl": "/v1/search?sport=NFL&include_props=false",
        "search_nba": "/v1/search?sport=NBA&include_props=false",
        "best12": "/v1/picks/best12",
        "best3": "/v1/parlays/best3",
        "parlay7": "/v1/parlays/multisport?legs=7",
        "parlay10": "/v1/parlays/multisport?legs=10",
        "parlay14": "/v1/parlays/multisport?legs=14",
    }

    payloads: dict[str, Any] = {}
    for name, path in static_checks.items():
        try:
            status, payload = get_json(args.base, path)
            payloads[name] = payload
            checks[name] = {"status": status, "object": isinstance(payload, dict)}
            if status != 200 or not isinstance(payload, dict):
                failures.append(name)
        except Exception as exc:
            checks[name] = {"error": f"{type(exc).__name__}: {exc}"}
            failures.append(name)

    status_doc = payloads.get("system_status")
    if isinstance(status_doc, dict):
        if status_doc.get("manual_review_only") is False:
            failures.append("manual_review_only")
        checks["market_baseline_only"] = status_doc.get("market_baseline_only")

    event_id = None
    search = payloads.get("search_nfl")
    if isinstance(search, dict) and isinstance(search.get("games"), list):
        for row in search["games"]:
            if isinstance(row, dict) and row.get("event_id") is not None:
                event_id = str(row["event_id"])
                break

    if event_id:
        encoded = urllib.parse.quote(event_id, safe="")
        dynamic = {
            "game_detail": f"/v1/games/NFL/{encoded}",
            "game_props": f"/v1/games/NFL/{encoded}/props",
            "game_best9": f"/v1/games/NFL/{encoded}/best9",
        }
        for name, path in dynamic.items():
            try:
                status, payload = get_json(args.base, path)
                checks[name] = {"status": status, "object": isinstance(payload, dict)}
                # A provider/evidence gate may legitimately block a specific game,
                # but a migrated runtime must never report route-not-found.
                if status in {404, 405} or not isinstance(payload, dict):
                    failures.append(name)
            except Exception as exc:
                checks[name] = {"error": f"{type(exc).__name__}: {exc}"}
                failures.append(name)
    else:
        checks["dynamic_game_routes"] = "No current NFL event; OpenAPI route-presence check used."

    report = {
        "base": args.base,
        "passed": not failures,
        "failures": sorted(set(failures)),
        "checks": checks,
    }
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
