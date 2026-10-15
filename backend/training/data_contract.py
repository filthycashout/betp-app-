from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

SPORTS = ("NFL", "NBA", "MLB", "NHL")
CONTRACT_VERSION = "1"


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PregameSnapshot(BaseModel):
    model_config = ConfigDict(extra="allow")

    sport: Literal["NFL", "NBA", "MLB", "NHL"]
    event_id: str = Field(min_length=1)
    event_time: datetime
    as_of: datetime
    home_team: str = Field(min_length=1)
    away_team: str = Field(min_length=1)
    market_home_probability: float | None = None

    @field_validator("sport", mode="before")
    @classmethod
    def normalize_sport(cls, value: Any) -> str:
        return str(value or "").strip().upper()

    @field_validator("event_id", "home_team", "away_team", mode="before")
    @classmethod
    def strip_required_text(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("event_time", "as_of")
    @classmethod
    def require_timezone(cls, value: datetime, info):
        return _aware(value, info.field_name)

    @field_validator("market_home_probability")
    @classmethod
    def probability_range(cls, value: float | None) -> float | None:
        if value is not None and not 0.0 < value < 1.0:
            raise ValueError("market_home_probability must be strictly between 0 and 1")
        return value

    @model_validator(mode="after")
    def chronology_and_teams(self):
        if not self.as_of < self.event_time:
            raise ValueError("pregame chronology requires as_of < event_time")
        if self.home_team.casefold() == self.away_team.casefold():
            raise ValueError("home_team and away_team must differ")
        return self


class CanonicalTrainingRow(PregameSnapshot):
    target_home_win: int
    label_available_at: datetime

    @field_validator("target_home_win")
    @classmethod
    def binary_target(cls, value: int) -> int:
        if value not in (0, 1):
            raise ValueError("target_home_win must be 0 or 1")
        return value

    @field_validator("label_available_at")
    @classmethod
    def label_time_timezone(cls, value: datetime) -> datetime:
        return _aware(value, "label_available_at")

    @model_validator(mode="after")
    def label_after_event(self):
        if not self.label_available_at > self.event_time:
            raise ValueError("label_available_at must be after event_time")
        return self


def _coerce_feature(value: Any, name: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(numeric):
        raise ValueError(f"{name} must be finite")
    return numeric


def validate_records(
    records: list[dict[str, Any]],
    *,
    mode: str,
    sport: str | None,
    features: list[str],
) -> dict[str, Any]:
    model = PregameSnapshot if mode == "pregame" else CanonicalTrainingRow
    normalized_sport = sport.strip().upper() if sport else None
    if normalized_sport and normalized_sport not in SPORTS:
        raise ValueError(f"Unsupported sport: {sport}")

    errors: list[dict[str, Any]] = []
    keys: set[tuple[str, str]] = set()
    duplicate_keys: list[str] = []
    validated = 0

    for index, raw in enumerate(records, start=1):
        try:
            row = model.model_validate(raw)
            if normalized_sport and row.sport != normalized_sport:
                raise ValueError(f"sport mismatch: expected {normalized_sport}, got {row.sport}")
            for feature in features:
                if feature not in raw:
                    raise ValueError(f"missing required feature: {feature}")
                _coerce_feature(raw.get(feature), feature)
            key = (row.sport, row.event_id)
            if key in keys:
                duplicate_keys.append(f"{row.sport}:{row.event_id}")
            keys.add(key)
            validated += 1
        except (ValidationError, ValueError) as exc:
            errors.append({"row": index, "error": str(exc)})

    if duplicate_keys:
        errors.append(
            {
                "row": None,
                "error": f"duplicate sport/event_id keys: {sorted(set(duplicate_keys))[:20]}",
            }
        )
    if errors:
        raise ValueError(
            json.dumps(
                {"contract_version": CONTRACT_VERSION, "errors": errors[:50]},
                indent=2,
                sort_keys=True,
            )
        )

    return {
        "contract_version": CONTRACT_VERSION,
        "mode": mode,
        "sport": normalized_sport,
        "rows": validated,
        "required_features": features,
        "status": "PASS",
    }


def read_records(path: Path, mode: str) -> list[dict[str, Any]]:
    if mode == "pregame":
        records = []
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSONL at line {line_number}: {exc}") from exc
                if not isinstance(value, dict):
                    raise ValueError(f"JSONL line {line_number} must be an object")
                records.append(value)
        return records

    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate PhilthyParleys sports data against a fail-closed contract"
    )
    parser.add_argument("--mode", choices=("pregame", "canonical"), required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--sport")
    parser.add_argument("--features", default="")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    features = [item.strip() for item in args.features.split(",") if item.strip()]
    records = read_records(args.input, args.mode)
    result = validate_records(records, mode=args.mode, sport=args.sport, features=features)
    result.update({"input": str(args.input), "input_sha256": _sha256(args.input)})

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
