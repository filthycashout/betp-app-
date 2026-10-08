#!/usr/bin/env python3
"""Fail-closed NFL/NBA promoted-model release validation.

Accepts either the canonical FastAPI /v1/models/status shape (sports at the
root) or an adapter shape that nests them under `models`, with optional
SuperJSON envelope. The runtime promotion gate remains authoritative: this
script verifies that its full check map is present and entirely true, while
also asserting the artifact actually loaded and is checksum-addressed.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

SPORTS = ("NFL", "NBA")
CRITICAL_CHECKS = {
    "canonical_dataset",
    "feature_schema",
    "chronology_as_of_before_event",
    "walk_forward_oof",
    "calibration_oof_only",
    "calibration_metrics",
    "ece_threshold",
    "separate_holdout",
    "leakage_audit",
    "provenance_hashes",
    "beats_active_market_baseline",
    "sample_sufficiency",
    "artifact_security",
    "mobile_parity",
    "trained_weights",
    "explicit_promotion",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.I)


def unwrap(value: Any) -> Any:
    if isinstance(value, dict) and set(value).issubset({"json", "meta"}) and "json" in value:
        return value["json"]
    return value


def load(path: Path) -> Any:
    return unwrap(json.loads(path.read_text(encoding="utf-8")))


def model_map(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    if all(isinstance(payload.get(sport), dict) for sport in SPORTS):
        return payload
    nested = payload.get("models")
    return nested if isinstance(nested, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-status", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("governed-model-readiness.json"))
    args = parser.parse_args()

    models = model_map(load(args.model_status))
    failures: list[str] = []
    verified: dict[str, Any] = {}

    for sport in SPORTS:
        row = models.get(sport) or models.get(sport.lower())
        if not isinstance(row, dict):
            failures.append(f"{sport}: structured model status missing")
            continue

        gate = row.get("promotion_gate") or {}
        checks = gate.get("checks") or {}
        missing = sorted(CRITICAL_CHECKS - set(checks)) if isinstance(checks, dict) else sorted(CRITICAL_CHECKS)
        failed = sorted(name for name, value in checks.items() if value is not True) if isinstance(checks, dict) else ["check_map_missing"]
        sha256 = row.get("sha256") or row.get("artifact_checksum") or ""
        loaded = row.get("promoted_artifact_loaded") is True
        runtime_mode = row.get("runtime_mode")

        if gate.get("passed") is not True:
            failures.append(f"{sport}: promotion gate is not passed")
        if not isinstance(checks, dict) or not checks:
            failures.append(f"{sport}: promotion check map missing")
        if missing:
            failures.append(f"{sport}: critical gate checks absent: {', '.join(missing)}")
        if failed:
            failures.append(f"{sport}: failed promotion checks: {', '.join(failed)}")
        if not loaded:
            failures.append(f"{sport}: promoted artifact is not loaded")
        if runtime_mode != "PROMOTED_TRAINED_MODEL":
            failures.append(f"{sport}: runtime mode is not PROMOTED_TRAINED_MODEL")
        if not isinstance(sha256, str) or not SHA256_RE.fullmatch(sha256):
            failures.append(f"{sport}: valid artifact SHA-256 missing")

        verified[sport] = {
            "promotion_gate_passed": gate.get("passed") is True,
            "critical_checks_present": not missing,
            "all_runtime_checks_passed": not failed and bool(checks),
            "promoted_artifact_loaded": loaded,
            "runtime_mode": runtime_mode,
            "sha256_valid": isinstance(sha256, str) and bool(SHA256_RE.fullmatch(sha256)),
            "checks": checks,
        }

    report = {
        "release_gate_passed": not failures,
        "sports": verified,
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["release_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
