from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SPORTS = {"NFL", "NBA", "MLB", "NHL"}
REGISTRY_VERSION = 1


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def verify_artifact(artifact: dict[str, Any], sport: str) -> dict[str, str]:
    if artifact.get("status") != "PROMOTED_TRAINED_MODEL":
        raise ValueError(
            "Only PROMOTED_TRAINED_MODEL artifacts may enter the immutable registry"
        )
    if str(artifact.get("sport") or "").upper() != sport:
        raise ValueError(f"Artifact sport mismatch: expected {sport}")

    artifact_sha = str(artifact.get("artifact_sha256") or "").lower()
    if len(artifact_sha) != 64 or any(c not in "0123456789abcdef" for c in artifact_sha):
        raise ValueError("artifact_sha256 missing or malformed")

    unsigned_payload = {
        key: value
        for key, value in artifact.items()
        if key not in {"artifact_sha256", "signature"}
    }
    if _sha256(_canonical(unsigned_payload)) != artifact_sha:
        raise ValueError("artifact_sha256 does not match canonical promoted artifact core")

    signature = artifact.get("signature") or {}
    signed_core_sha = str(signature.get("signed_core_sha256") or "").lower()
    if len(signed_core_sha) != 64:
        raise ValueError("signed_core_sha256 missing")
    signed_payload = {key: value for key, value in artifact.items() if key != "signature"}
    if _sha256(_canonical(signed_payload)) != signed_core_sha:
        raise ValueError("signed_core_sha256 does not match signed artifact payload")
    for key in ("key_id", "public_key_b64", "signature_b64"):
        if not signature.get(key):
            raise ValueError(f"signature.{key} missing")

    evidence = artifact.get("promotion_evidence") or {}
    provenance = evidence.get("provenance") or {}
    dataset_sha = str(provenance.get("dataset_sha256") or "").lower()
    feature_schema_sha = str(provenance.get("feature_schema_sha256") or "").lower()
    for name, value in (
        ("dataset_sha256", dataset_sha),
        ("feature_schema_sha256", feature_schema_sha),
    ):
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError(
                f"promotion_evidence.provenance.{name} missing or malformed"
            )

    return {
        "artifact_sha256": artifact_sha,
        "signed_core_sha256": signed_core_sha,
        "dataset_sha256": dataset_sha,
        "feature_schema_sha256": feature_schema_sha,
    }


def register(artifact_path: Path, registry_root: Path, sport: str) -> dict[str, Any]:
    sport = sport.upper().strip()
    if sport not in SPORTS:
        raise ValueError(f"Unsupported sport: {sport}")

    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    verified = verify_artifact(artifact, sport)

    sport_dir = registry_root / sport.lower()
    sport_dir.mkdir(parents=True, exist_ok=True)
    immutable_path = sport_dir / f"{verified['artifact_sha256']}.json"
    payload = json.dumps(artifact, indent=2, sort_keys=True) + "\n"
    if immutable_path.exists() and immutable_path.read_text(encoding="utf-8") != payload:
        raise ValueError(f"Immutable registry collision at {immutable_path}")
    immutable_path.write_text(payload, encoding="utf-8")

    index_path = registry_root / "index.json"
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
    else:
        index = {"registry_version": REGISTRY_VERSION, "sports": {}}
    if index.get("registry_version") != REGISTRY_VERSION:
        raise ValueError("Unsupported registry version")

    sport_index = index.setdefault("sports", {}).setdefault(
        sport,
        {"artifacts": [], "active": None},
    )
    entries = sport_index.setdefault("artifacts", [])
    if not any(
        item.get("artifact_sha256") == verified["artifact_sha256"]
        for item in entries
    ):
        entries.append(
            {
                **verified,
                "model_id": artifact.get("model_id"),
                "model_type": artifact.get("model_type"),
                "schema_version": artifact.get("schema_version"),
                "path": immutable_path.as_posix(),
                "registered_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    entries.sort(
        key=lambda item: (
            str(item.get("registered_at") or ""),
            item["artifact_sha256"],
        )
    )
    sport_index["active"] = verified["artifact_sha256"]
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return {
        "sport": sport,
        "registry": str(index_path),
        "immutable_artifact": str(immutable_path),
        **verified,
        "status": "REGISTERED",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Register a signed PhilthyParleys model as an immutable "
            "content-addressed artifact"
        )
    )
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--registry-root", required=True, type=Path)
    parser.add_argument("--sport", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            register(args.artifact, args.registry_root, args.sport),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
