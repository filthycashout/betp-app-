from __future__ import annotations

import argparse
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def get_json(url: str, attempts: int = 10, delay: int = 12):
    last = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(
                url,
                headers={"Accept": "application/json", "User-Agent": "PhilthyParleys-production-guard/1.1"},
            )
            with urllib.request.urlopen(req, timeout=20) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}")
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
            if attempt + 1 < attempts:
                time.sleep(delay)
    raise RuntimeError(last or "request failed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base,
        "passed": False,
        "checks": {},
    }
    try:
        health = get_json(base + "/health")
        status = get_json(base + "/v1/system/status")
        props = get_json(base + "/v1/system/props")
        providers = get_json(base + "/v1/data/external-providers")
        evidence = get_json(base + "/v1/evidence/signals?limit=1")
        storage = evidence.get("storage_status") or {}

        gateway = providers.get("free_odds_gateway") or {}
        snapshot_storage = gateway.get("snapshot_storage") or {}
        checks = {
            "health_ok": health.get("status") == "ok",
            "service_identity": health.get("service") == "philthysports-runtime",
            "core_keyless": (status.get("gates") or {}).get("credential_core_keyless") == "PASS",
            "stable_android_signing": str((status.get("gates") or {}).get("stable_android_signing") or "").startswith("PASS"),
            "immutable_capture": str((status.get("gates") or {}).get("immutable_pregame_evidence_capture") or "").startswith("PASS"),
            "keyless_props_fallback": props.get("keyless_fallback_configured") is True,
            "free_odds_gateway_identity": gateway.get("name") == "PhilthySports FreeOddsGateway",
            "free_odds_gateway_oddswrap": (gateway.get("oddswrap") or {}).get("available") is True,
            "free_odds_gateway_snapshot_gate": gateway.get("snapshot_gate") == "fetched_at < event_time",
            "free_odds_gateway_snapshot_database_configured": snapshot_storage.get("database_configured") is True,
            "free_odds_gateway_snapshot_storage_durable": snapshot_storage.get("durable") is True,
            "free_odds_gateway_snapshot_storage_postgres": snapshot_storage.get("mode") in {"postgres", "render_postgres"},
            "free_odds_gateway_props_chain": gateway.get("player_props_order") == ["ODDSWRAP", "PROPLINE", "ODDS_API_IO"],
            "manual_review_only": status.get("execution_mode") == "MANUAL_REVIEW_ONLY",
            "evidence_database_configured": storage.get("database_configured") is True,
            "evidence_durable": evidence.get("durable_storage") is True and storage.get("durable") is True,
            "evidence_postgres": storage.get("mode") in {"postgres", "render_postgres"},
            "evidence_database_error_clear": storage.get("database_error_type") in (None, ""),
        }
        report.update(
            api_version=status.get("api_version"),
            gates=status.get("gates"),
            credential_gate=status.get("credential_gate"),
            props_status=props.get("status"),
            free_odds_gateway=gateway,
            market_snapshot_storage=snapshot_storage,
            evidence_storage={
                "storage_root": evidence.get("storage_root"),
                "durable_storage": evidence.get("durable_storage"),
                "storage_status": storage,
            },
            checks=checks,
            passed=all(checks.values()),
        )
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit(0 if report["passed"] else 2)


if __name__ == "__main__":
    main()
