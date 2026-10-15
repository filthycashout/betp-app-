from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

SPORTS = {"NFL", "NBA", "MLB", "NHL"}
DRIVE_REQUIRED = {
    "sport",
    "event_id",
    "event_time",
    "snapshot_time",
    "settled_time",
    "target",
    "market_prob",
    "consensus_de_vig_home_probability",
    "home_spread",
    "consensus_total",
}
TRAINER_REQUIRED = {
    "sport",
    "event_id",
    "event_time",
    "as_of",
    "home_team",
    "away_team",
    "target_home_win",
    "market_home_probability",
    "label_available_at",
}
FORBIDDEN_FEATURE_TOKENS = {
    "target",
    "winner",
    "won",
    "final",
    "postgame",
    "result",
    "outcome",
    "home_score",
    "away_score",
    "live_win",
    "live_score",
    "settled",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CanonicalAdmissionError(ValueError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _times(frame: pd.DataFrame, column: str) -> pd.Series:
    try:
        values = pd.to_datetime(frame[column], utc=True, errors="raise")
    except Exception as exc:
        raise CanonicalAdmissionError(f"invalid UTC timestamp column {column}") from exc
    return values


def model_feature_columns(frame: pd.DataFrame) -> list[str]:
    return [
        column
        for column in frame.columns
        if column.startswith("feature_") and not column.endswith("_observed_at")
    ]


def normalize_drive_frame(frame: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(DRIVE_REQUIRED - set(frame.columns))
    if missing:
        raise CanonicalAdmissionError(f"Sports Omni dataset missing columns: {missing}")
    result = frame.copy()
    result["sport"] = result["sport"].astype(str).str.upper().str.strip()
    if not set(result["sport"].unique()).issubset(SPORTS):
        raise CanonicalAdmissionError("unsupported sport in canonical dataset")
    if result["sport"].nunique() != 1:
        raise CanonicalAdmissionError("Sports Omni canonical training files must contain exactly one sport")
    if result["event_id"].isna().any() or (result["event_id"].astype(str).str.strip() == "").any():
        raise CanonicalAdmissionError("event_id must be present")
    if result["event_id"].astype(str).duplicated().any():
        raise CanonicalAdmissionError("event_id must be unique within a sport dataset")

    event_time = _times(result, "event_time")
    snapshot_time = _times(result, "snapshot_time")
    settled_time = _times(result, "settled_time")
    if not bool((snapshot_time < event_time).all()):
        raise CanonicalAdmissionError("snapshot_time must precede event_time for every row")
    if not bool((settled_time > event_time).all()):
        raise CanonicalAdmissionError("settled_time must follow event_time for every row")

    result["target"] = pd.to_numeric(result["target"], errors="raise")
    if not set(result["target"].unique()).issubset({0, 1}):
        raise CanonicalAdmissionError("target must be binary 0/1")
    for column in (
        "market_prob",
        "consensus_de_vig_home_probability",
        "home_spread",
        "consensus_total",
    ):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if result["market_prob"].isna().any() or not bool(result["market_prob"].between(0, 1, inclusive="neither").all()):
        raise CanonicalAdmissionError("market_prob must be present and strictly between zero and one")
    if result["consensus_de_vig_home_probability"].isna().any() or not bool(
        result["consensus_de_vig_home_probability"].between(0, 1, inclusive="neither").all()
    ):
        raise CanonicalAdmissionError("consensus_de_vig_home_probability must be present and strictly between zero and one")

    features = model_feature_columns(result)
    bad = [
        column
        for column in features
        if any(token in column.lower() for token in FORBIDDEN_FEATURE_TOKENS)
    ]
    if bad:
        raise CanonicalAdmissionError(f"leakage-prone feature names rejected: {bad}")
    for feature in features:
        result[feature] = pd.to_numeric(result[feature], errors="raise")
        observed = f"{feature}_observed_at"
        if observed in result.columns:
            observed_time = _times(result, observed)
            if bool((observed_time > snapshot_time).any()):
                raise CanonicalAdmissionError(f"feature observation occurs after snapshot: {feature}")
    return result


def to_trainer_contract(frame: pd.DataFrame) -> pd.DataFrame:
    result = normalize_drive_frame(frame)
    mapping = {
        "snapshot_time": "as_of",
        "settled_time": "label_available_at",
        "target": "target_home_win",
        "market_prob": "market_home_probability",
    }
    result = result.rename(columns=mapping)
    if "home_team" not in result.columns or "away_team" not in result.columns:
        raise CanonicalAdmissionError("home_team and away_team are required before trainer admission")
    missing = sorted(TRAINER_REQUIRED - set(result.columns))
    if missing:
        raise CanonicalAdmissionError(f"trainer contract missing columns: {missing}")
    return result


def admit_csv(
    source_csv: Path,
    source_manifest: Path,
    output_csv: Path,
    output_manifest: Path,
) -> dict[str, Any]:
    source = json.loads(source_manifest.read_text(encoding="utf-8"))
    expected_sha = str(source.get("sha256") or source.get("dataset_sha256") or "").lower()
    actual_sha = _sha256(source_csv)
    if not SHA256_RE.fullmatch(expected_sha) or expected_sha != actual_sha:
        raise CanonicalAdmissionError("source manifest checksum does not match incoming dataset")
    if source.get("promotion_eligible") is True:
        # Incoming material can never self-declare promotion authority.
        raise CanonicalAdmissionError("incoming source may not self-declare promotion_eligible=true")
    if not source.get("source"):
        raise CanonicalAdmissionError("source manifest must identify provenance")

    frame = pd.read_csv(source_csv)
    trainer = to_trainer_contract(frame)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    trainer.to_csv(output_csv, index=False)
    output = {
        "schema_version": "sports-omni-to-governed-trainer-v1",
        "source": str(source.get("source")),
        "source_dataset_sha256": actual_sha,
        "trainer_dataset_sha256": _sha256(output_csv),
        "sport": str(trainer["sport"].iloc[0]),
        "rows": len(trainer),
        "features": model_feature_columns(trainer),
        "admitted_at": datetime.now(timezone.utc).isoformat(),
        "chronology": {
            "snapshot_before_event": True,
            "settlement_after_event": True,
            "feature_observed_at_not_after_snapshot": True,
        },
        "authority": {
            "promotion_eligible": False,
            "candidate_only": True,
            "requires_governed_training_and_strict_promotion": True,
        },
    }
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    output_manifest.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output
