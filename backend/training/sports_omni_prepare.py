from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from training.point_in_time_features import build_csv
from training.sports_omni_contract import CanonicalAdmissionError, admit_csv


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(
    source_csv: Path,
    source_manifest: Path,
    output_dir: Path,
) -> dict[str, Any]:
    source = json.loads(source_manifest.read_text(encoding="utf-8"))
    expected_sha = str(source.get("sha256") or source.get("dataset_sha256") or "").lower()
    actual_sha = _sha256(source_csv)
    if expected_sha != actual_sha:
        raise CanonicalAdmissionError("incoming source manifest checksum mismatch")
    if source.get("promotion_eligible") is True:
        raise CanonicalAdmissionError("incoming source cannot self-declare promotion eligibility")
    if not source.get("source"):
        raise CanonicalAdmissionError("incoming source manifest must identify provenance")

    output_dir.mkdir(parents=True, exist_ok=True)
    enriched_csv = output_dir / f"{source_csv.stem}_point_in_time.csv"
    feature_report = build_csv(source_csv, enriched_csv)
    enriched_manifest = output_dir / f"{source_csv.stem}_point_in_time_source_manifest.json"
    derived = {
        "schema_version": "sports-omni-derived-features-v1",
        "source": f"derived point-in-time features from {source.get('source')}",
        "sha256": _sha256(enriched_csv),
        "parent_dataset": str(source_csv),
        "parent_dataset_sha256": actual_sha,
        "parent_manifest": str(source_manifest),
        "feature_report": feature_report,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "promotion_eligible": False,
        "candidate_only": True,
        "derivation_rule": (
            "market fields are snapshot-time features; team-history features use only prior events whose "
            "settled_time precedes the current prediction snapshot"
        ),
    }
    enriched_manifest.write_text(json.dumps(derived, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    trainer_csv = output_dir / f"{source_csv.stem}_trainer.csv"
    trainer_manifest = output_dir / f"{source_csv.stem}_trainer_manifest.json"
    admission = admit_csv(enriched_csv, enriched_manifest, trainer_csv, trainer_manifest)
    sport = admission["sport"]
    feature_arg = ",".join(admission["features"])
    if not feature_arg:
        raise CanonicalAdmissionError("preparation produced no numeric model features")
    command = (
        f"PYTHONPATH=backend python backend/training/governed_train.py --sport {sport} "
        f"--input {trainer_csv} --source-manifest {trainer_manifest} "
        f"--features {feature_arg} --output-dir {output_dir / 'candidate'}"
    )
    return {
        "status": "PREPARED_CANDIDATE_ONLY",
        "source_dataset_sha256": actual_sha,
        "enriched_csv": str(enriched_csv),
        "enriched_manifest": str(enriched_manifest),
        "trainer_csv": str(trainer_csv),
        "trainer_manifest": str(trainer_manifest),
        "features": admission["features"],
        "admission": admission,
        "next_governed_training_command": command,
        "promotion_executed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare Sports Omni canonical evidence for governed training")
    parser.add_argument("--source-csv", required=True, type=Path)
    parser.add_argument("--source-manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source_csv, args.source_manifest, args.output_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
