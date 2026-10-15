from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

CLASSIFICATIONS = {
    "ADMISSIBLE_PREGAME",
    "SETTLEMENT_ONLY",
    "FEATURE_REFERENCE",
    "MODEL_REFERENCE",
    "LIVE_LEAKAGE",
    "SYNTHETIC",
    "DUPLICATE",
    "EMPTY",
    "SECRET_EXCLUDED",
    "ARCHIVE_ONLY",
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _classify(source: dict[str, Any]) -> str:
    role = str(source.get("role") or "").lower()
    title = str(source.get("title") or "").lower()
    combined = f"{role} {title}"
    proof = source.get("admission_proof") or {}

    if any(token in combined for token in ("credential", "secret", "keys.txt", ".env")):
        return "SECRET_EXCLUDED"
    if any(token in combined for token in ("live_adjust", "live_win", "in_play", "postgame_feature")):
        return "LIVE_LEAKAGE"
    if any(token in combined for token in ("synthetic", "random", "demo", "sample_generator")):
        return "SYNTHETIC"
    if "quarantined" in role or "model" in role or "preprocessor" in role:
        return "MODEL_REFERENCE"
    if role in {"settled_evaluation", "settlement", "settled_result"}:
        return "SETTLEMENT_ONLY"
    if role in {"feature_snapshot", "feature_dictionary", "experiment_summary", "provider_schema", "schema"}:
        return "FEATURE_REFERENCE"
    if (
        role in {"pregame_evidence", "market_snapshot"}
        and proof.get("as_of_lt_event_time") is True
        and proof.get("provenance_verified") is True
        and proof.get("immutable_hash_verified") is True
    ):
        return "ADMISSIBLE_PREGAME"
    return "ARCHIVE_ONLY"


def build(source_manifest: Path) -> dict[str, Any]:
    raw = json.loads(source_manifest.read_text(encoding="utf-8"))
    entries: list[dict[str, Any]] = []

    for sport, section in sorted((raw.get("sports") or {}).items()):
        for source in section.get("sources") or []:
            entries.append(
                {
                    "sport": sport,
                    "title": source.get("title"),
                    "drive_id": source.get("drive_id"),
                    "sha256": source.get("sha256"),
                    "size_bytes": source.get("size_bytes"),
                    "legacy_role": source.get("role"),
                    "classification": _classify(source),
                    "execute": False if str(source.get("role") or "").startswith("quarantined") else source.get("execute"),
                    "reason": (
                        "Legacy Drive material is evidence/reference only unless an explicit admission proof establishes immutable pregame chronology."
                    ),
                }
            )

    for item in raw.get("excluded_placeholder_folders") or []:
        entries.append(
            {
                "sport": None,
                "title": item.get("title"),
                "drive_id": None,
                "sha256": None,
                "size_bytes": None,
                "legacy_role": "placeholder_folder",
                "classification": "EMPTY",
                "execute": False,
                "reason": "Empty organizational shell; contains no recoverable training evidence.",
            }
        )

    by_hash: dict[str, list[int]] = defaultdict(list)
    for index, entry in enumerate(entries):
        digest = str(entry.get("sha256") or "").lower()
        if len(digest) == 64:
            by_hash[digest].append(index)
    for digest, indexes in by_hash.items():
        if len(indexes) <= 1:
            continue
        for index in indexes[1:]:
            entries[index]["classification"] = "DUPLICATE"
            entries[index]["duplicate_of_sha256"] = digest
            entries[index]["execute"] = False

    counts = Counter(entry["classification"] for entry in entries)
    output = {
        "manifest_version": "2",
        "source_manifest": str(source_manifest),
        "source_manifest_sha256": hashlib.sha256(source_manifest.read_bytes()).hexdigest(),
        "canonical_drive_home": "Sports_Omni_Project",
        "classifications": sorted(CLASSIFICATIONS),
        "admission_rule": (
            "Legacy artifacts never become training authority from filename, model output, or apparent plausibility. "
            "ADMISSIBLE_PREGAME requires explicit chronology, provenance, and immutable-hash proof."
        ),
        "automatic_wagering": False,
        "counts": dict(sorted(counts.items())),
        "entries": entries,
    }
    output["manifest_sha256"] = hashlib.sha256(_canonical(output)).hexdigest()
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize/classify the legacy Allspice/Drive recovery inventory")
    parser.add_argument("--source", type=Path, default=Path(__file__).with_name("drive_reconstruction_manifest.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = build(args.source)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
