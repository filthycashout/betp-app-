#!/usr/bin/env python3
"""Deterministic repository-state audit for PhilthyParleys.

This audit enforces state semantics that are easy to blur in documentation:

- code exists != promoted model
- legacy model file != promoted model
- notebook complete != promoted/available external model
- baseline artifact != trained promoted model
- configured automation != observed successful runtime execution

Promotion authority remains in ``backend/model_runtime.py``. A sport is treated as
promoted only when ``load_promoted`` accepts the signed JSON artifact through the
full deterministic promotion gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

SPORTS = ("NFL", "NBA", "MLB", "NHL")
ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
MODELS = BACKEND / "models"
PROMOTED = MODELS / "promoted"


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo_paths(patterns: tuple[str, ...]) -> list[str]:
    found: set[str] = set()
    for pattern in patterns:
        for path in ROOT.rglob(pattern):
            if any(part in {".git", ".dart_tool", "build", "__pycache__"} for part in path.parts):
                continue
            found.add(path.relative_to(ROOT).as_posix())
    return sorted(found)


def audit() -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []

    manifest_path = MODELS / "manifest.json"
    candidates_path = MODELS / "candidate_registry.json"
    manifest = _read_json(manifest_path)
    candidates = _read_json(candidates_path)

    if manifest.get("status") != "PRODUCTION_BASELINE":
        failures.append("backend/models/manifest.json must identify the baseline bundle as PRODUCTION_BASELINE")
    if manifest.get("trained_weights") is not False:
        failures.append("baseline manifest must keep trained_weights=false")

    baseline: dict[str, Any] = {}
    manifest_sports = manifest.get("sports") or {}
    for sport in SPORTS:
        entry = manifest_sports.get(sport)
        if not isinstance(entry, dict):
            failures.append(f"baseline manifest missing {sport}")
            continue
        rel = entry.get("path")
        expected_sha = entry.get("sha256")
        path = ROOT / str(rel or "")
        row: dict[str, Any] = {
            "path": str(rel or ""),
            "exists": path.is_file(),
            "manifest_sha256": expected_sha,
            "actual_sha256": None,
            "status": None,
            "trained_weights": None,
            "manual_review_only": None,
        }
        if not path.is_file():
            failures.append(f"missing baseline artifact for {sport}: {rel}")
            baseline[sport] = row
            continue
        actual_sha = _sha256(path)
        row["actual_sha256"] = actual_sha
        if expected_sha != actual_sha:
            failures.append(f"baseline checksum mismatch for {sport}")
        artifact = _read_json(path)
        row["status"] = artifact.get("status")
        row["trained_weights"] = artifact.get("trained_weights")
        row["manual_review_only"] = artifact.get("manual_review_only")
        if artifact.get("sport") != sport:
            failures.append(f"baseline sport identity mismatch for {sport}")
        if artifact.get("status") != "PRODUCTION_BASELINE":
            failures.append(f"{sport} baseline artifact cannot claim promoted status")
        if artifact.get("trained_weights") is not False:
            failures.append(f"{sport} baseline artifact must keep trained_weights=false")
        if artifact.get("manual_review_only") is not True:
            failures.append(f"{sport} baseline artifact must remain manual_review_only=true")
        baseline[sport] = row

    sys.path.insert(0, str(BACKEND))
    runtime_import_error: str | None = None
    try:
        import model_runtime  # type: ignore
    except Exception as exc:  # pragma: no cover - exercised by environment failures
        model_runtime = None  # type: ignore
        runtime_import_error = f"{type(exc).__name__}: {exc}"
        failures.append(f"could not import model_runtime for promotion verification: {runtime_import_error}")

    promoted: dict[str, Any] = {}
    candidate_sports = candidates.get("sports") or {}
    for sport in SPORTS:
        alias = PROMOTED / f"{sport.lower()}.json"
        runtime_accepted = False
        runtime_model_id = None
        gate_failures: list[str] = []
        if model_runtime is not None:
            accepted = model_runtime.load_promoted(sport)
            runtime_accepted = accepted is not None
            if accepted is not None:
                runtime_model_id = accepted.get("model_id")
            elif alias.is_file():
                try:
                    raw = _read_json(alias)
                    gate = model_runtime.promotion_gate(raw, sport)
                    gate_failures = [key for key, value in (gate.get("checks") or {}).items() if not value]
                except Exception as exc:
                    gate_failures = [f"unreadable_or_invalid:{type(exc).__name__}"]

        if alias.is_file() and not runtime_accepted:
            failures.append(
                f"{sport} promoted alias exists but runtime gate rejects it; file existence is not promotion"
            )
        if runtime_accepted:
            raw = _read_json(alias)
            if raw.get("status") != "PROMOTED_TRAINED_MODEL" or raw.get("trained_weights") is not True:
                failures.append(f"{sport} runtime-accepted promoted artifact has inconsistent status/trained_weights")

        candidate = candidate_sports.get(sport) if isinstance(candidate_sports, dict) else None
        promoted[sport] = {
            "alias_path": alias.relative_to(ROOT).as_posix(),
            "alias_exists": alias.is_file(),
            "runtime_accepted": runtime_accepted,
            "runtime_model_id": runtime_model_id,
            "gate_failures_if_present": gate_failures,
            "legacy_candidate_state": candidate,
        }

    legacy_model_files = _repo_paths(("*.joblib", "*.pkl", "*.pickle", "*.sav"))
    notebook_files = _repo_paths(("*.ipynb", "*.ipynb_ready.txt"))
    promoted_non_json = [
        path for path in legacy_model_files + notebook_files
        if path.startswith("backend/models/promoted/")
    ]
    if promoted_non_json:
        failures.append(
            "legacy/notebook artifacts must never be placed in backend/models/promoted: "
            + ", ".join(promoted_non_json)
        )

    code_paths = {
        "trainer": "backend/training/governed_train.py",
        "strict_promoter": "backend/training/strict_promote.py",
        "signer_client": "backend/training/sign_promoted.py",
        "immutable_registry": "backend/training/register_artifact.py",
        "runtime_gate": "backend/model_runtime.py",
        "evidence_admission": "backend/training/evidence_admission.py",
    }
    code_exists = {name: (ROOT / rel).is_file() for name, rel in code_paths.items()}
    for name, exists in code_exists.items():
        if not exists:
            failures.append(f"required governed component missing: {name} -> {code_paths[name]}")

    dockerfile = BACKEND / "Dockerfile"
    compose = ROOT / "deploy" / "docker-compose.prod.yml"
    evidence_workflow = ROOT / ".github" / "workflows" / "v8-evidence-capture.yml"
    train_workflow = ROOT / ".github" / "workflows" / "v8-train-promote.yml"
    docker_text = dockerfile.read_text(encoding="utf-8") if dockerfile.is_file() else ""
    compose_text = compose.read_text(encoding="utf-8") if compose.is_file() else ""
    evidence_text = evidence_workflow.read_text(encoding="utf-8") if evidence_workflow.is_file() else ""
    train_text = train_workflow.read_text(encoding="utf-8") if train_workflow.is_file() else ""

    automation = {
        "dockerfile_present": dockerfile.is_file(),
        "docker_healthcheck_configured": "HEALTHCHECK" in docker_text,
        "compose_present": compose.is_file(),
        "compose_restart_policy_configured": "restart: unless-stopped" in compose_text,
        "manual_review_only_configured": 'PHILTHY_MANUAL_REVIEW_ONLY: "true"' in compose_text,
        "evidence_capture_workflow_present": evidence_workflow.is_file(),
        "evidence_capture_scheduled": "cron:" in evidence_text,
        "training_workflow_present": train_workflow.is_file(),
        "training_workflow_scheduled": "cron:" in train_text,
    }
    for key, value in automation.items():
        if not value:
            failures.append(f"automation contract missing: {key}")

    current_promoted = [sport for sport, row in promoted.items() if row["runtime_accepted"]]
    if not current_promoted:
        warnings.append("No sport-specific trained model is currently accepted by the runtime promotion gate.")

    return {
        "contract_version": 1,
        "status": "PASS" if not failures else "FAIL",
        "invariants": {
            "code_exists_is_promoted_model": False,
            "legacy_model_file_is_promoted_model": False,
            "notebook_complete_is_promoted_model": False,
            "baseline_artifact_is_promoted_model": False,
            "configured_automation_is_observed_success": False,
            "promotion_authority": "backend/model_runtime.py::load_promoted + promotion_gate",
            "notebook_complete_definition": (
                "The notebook performs its intended notebook-level job; this does not imply that an external API, "
                "GPU model, local server, or sport-specific prediction model is currently available or promoted."
            ),
        },
        "baseline": baseline,
        "promoted": promoted,
        "runtime_accepted_promoted_sports": current_promoted,
        "candidate_registry_path": candidates_path.relative_to(ROOT).as_posix(),
        "legacy_model_files_in_repo": legacy_model_files,
        "notebook_files_in_repo": notebook_files,
        "governed_code": {
            name: {"path": code_paths[name], "exists": exists, "promotion_authority": False}
            for name, exists in code_exists.items()
        },
        "automation": automation,
        "runtime_import_error": runtime_import_error,
        "external_source_boundary": {
            "employment_job_boards": [
                "workinsports.com",
                "teamworkonline.com",
                "globalsportsjobs.com",
                "jobsinsports.com",
            ],
            "classification": "EMPLOYMENT_DISCOVERY_ONLY",
            "training_authority": False,
            "promotion_authority": False,
        },
        "failures": failures,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    report = audit()
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text, end="")
    return 1 if args.strict and report["status"] != "PASS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
