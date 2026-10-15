from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from data_contract import validate_records

SPORTS = ("NFL", "NBA", "MLB", "NHL")
ALLOWED_RESULT_SOURCES = {"ESPN scoreboard", "MLB Stats API", "NHL Web API"}
FEATURES = ["consensus_de_vig_home_probability", "home_spread", "consensus_total"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{number} is not an object")
        out.append(value)
    return out


def _csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def audit(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    captures: list[dict[str, Any]] = []
    pregame_rows: list[dict[str, Any]] = []

    for rows_path in sorted((root / "pregame").rglob("pregame_*.jsonl")):
        manifest_path = rows_path.with_name(rows_path.name.replace("pregame_", "manifest_").replace(".jsonl", ".json"))
        if not manifest_path.exists():
            errors.append(f"missing capture manifest for {rows_path}")
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        raw_path = rows_path.parent / str((manifest.get("raw_file") or {}).get("name") or "")
        if not raw_path.exists():
            errors.append(f"missing raw capture for {rows_path}")
            continue
        if _sha256(rows_path) != (manifest.get("rows_file") or {}).get("sha256"):
            errors.append(f"rows checksum mismatch: {rows_path}")
            continue
        if _sha256(raw_path) != (manifest.get("raw_file") or {}).get("sha256"):
            errors.append(f"raw checksum mismatch: {raw_path}")
            continue
        rows = _jsonl(rows_path)
        try:
            validate_records(rows, mode="pregame", sport=None, features=[])
        except ValueError as exc:
            errors.append(f"pregame contract failed {rows_path}: {exc}")
            continue
        pregame_rows.extend(rows)
        captures.append({
            "classification": "ADMISSIBLE_PREGAME",
            "rows_file": str(rows_path.relative_to(root)),
            "rows_sha256": _sha256(rows_path),
            "raw_file": str(raw_path.relative_to(root)),
            "raw_sha256": _sha256(raw_path),
            "rows": len(rows),
        })

    by_event: dict[tuple[str, str], dict[str, Any]] = {}
    for row in pregame_rows:
        key = (str(row.get("sport") or ""), str(row.get("event_id") or ""))
        existing = by_event.get(key)
        if existing is None or str(row.get("as_of") or "") > str(existing.get("as_of") or ""):
            by_event[key] = row

    labels_path = root / "settled" / "labels.jsonl"
    settlements = _jsonl(labels_path)
    settlement_rows = 0
    for label in settlements:
        key = (str(label.get("sport") or ""), str(label.get("event_id") or ""))
        source = label.get("result_source")
        if source not in ALLOWED_RESULT_SOURCES:
            errors.append(f"unapproved settlement source for {key}: {source}")
            continue
        event = by_event.get(key)
        if event is None:
            # Historical rows may be admitted through separately checksummed backfill manifests.
            continue
        candidate = {
            **event,
            "target_home_win": label.get("target_home_win"),
            "label_available_at": label.get("settled_at"),
            "settlement_observed_at": label.get("settled_at"),
            "settlement_source": source,
            "settlement_source_event_id": label.get("settlement_source_event_id") or label.get("event_id"),
            "final_home_score": label.get("final_home_score"),
            "final_away_score": label.get("final_away_score"),
            "settlement_status": label.get("settlement_status") or "SETTLED_FINAL",
            "settlement_payload_sha256": label.get("settlement_payload_sha256"),
        }
        try:
            validate_records([candidate], mode="canonical", sport=key[0], features=[])
            settlement_rows += 1
        except ValueError as exc:
            errors.append(f"settlement contract failed {key}: {exc}")

    canonical: dict[str, Any] = {}
    for sport in SPORTS:
        csv_path = root / "canonical" / f"{sport.lower()}.csv"
        manifest_path = root / "canonical" / f"{sport.lower()}_source_manifest.json"
        if not csv_path.exists() or not manifest_path.exists():
            errors.append(f"missing canonical bundle for {sport}")
            continue
        rows = _csv(csv_path)
        try:
            validation = validate_records(rows, mode="canonical", sport=sport, features=FEATURES)
        except ValueError as exc:
            errors.append(f"canonical contract failed {sport}: {exc}")
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = str(manifest.get("canonical_sha256") or "").lower()
        actual = _sha256(csv_path)
        if expected != actual:
            errors.append(f"canonical manifest checksum mismatch for {sport}")
            continue
        canonical[sport] = {
            "classification": "CANONICAL_EVIDENCE",
            "rows": len(rows),
            "canonical_sha256": actual,
            "source_manifest_sha256": _sha256(manifest_path),
            "contract": validation,
        }

    report = {
        "admission_version": "1",
        "status": "FAIL" if errors else "PASS",
        "automatic_wagering": False,
        "rules": {
            "pregame": "immutable checksummed capture + as_of/quote before event start",
            "settlement": "approved sports result source observed after event start; scores are verified when supplied",
            "canonical": "contract-valid canonical CSV whose SHA-256 matches its source manifest",
            "model_promotion": "separate downstream gate; admission alone never promotes a model",
        },
        "captures": captures,
        "settlement_rows_verified": settlement_rows,
        "canonical": canonical,
        "errors": errors,
    }
    if errors:
        raise ValueError(json.dumps(report, indent=2, sort_keys=True))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit evidence admission before chronological training")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = audit(args.root)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
