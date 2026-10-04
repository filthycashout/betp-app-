from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def get_json(url: str, attempts: int = 10, delay: int = 12):
    last = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(
                url,
                headers={"Accept": "application/json", "User-Agent": "PhilthyParleys-production-guard/1.0"},
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

        checks = {
            "health_ok": health.get("status") == "ok",
            "service_identity": health.get("service") == "philthysports-runtime",
            "core_keyless": (status.get("gates") or {}).get("credential_core_keyless") == "PASS",
            "stable_android_signing": str((status.get("gates") or {}).get("stable_android_signing") or "").startswith("PASS"),
            "immutable_capture": str((status.get("gates") or {}).get("immutable_pregame_evidence_capture") or "").startswith("PASS"),
            "keyless_props_fallback": props.get("keyless_fallback_configured") is True,
            "manual_review_only": status.get("execution_mode") == "MANUAL_REVIEW_ONLY",
        }
        report.update(
            api_version=status.get("api_version"),
            gates=status.get("gates"),
            credential_gate=status.get("credential_gate"),
            props_status=props.get("status"),
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
