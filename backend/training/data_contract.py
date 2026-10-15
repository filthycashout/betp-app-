from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

SPORTS = ("NFL", "NBA", "MLB", "NHL")
CONTRACT_VERSION = "2"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class PregameSnapshot(BaseModel):
    """Contract for a point-in-time market observation made before event start.

    Provider/market identifiers are optional because some upstreams do not expose a
    stable market-level ID. When present they are preserved, never synthesized.
    """

    model_config = ConfigDict(extra="allow")

    schema_version: str | int | None = None
    sport: Literal["NFL", "NBA", "MLB", "NHL"]
    event_id: str = Field(min_length=1)
    provider_event_id: str | None = None
    provider_market_id: str | None = None
    market_type: str | None = None
    selection: str | None = None
    line: float | None = None
    american_price: float | None = None
    book: str | None = None
    provider: str | None = None
    event_time: datetime
    event_started_at: datetime | None = None
    as_of: datetime
    quote_captured_at: datetime | None = None
    home_team: str = Field(min_length=1)
    away_team: str = Field(min_length=1)
    market_home_probability: float | None = None
    raw_snapshot_sha256: str | None = None

    @field_validator("sport", mode="before")
    @classmethod
    def normalize_sport(cls, value: Any) -> str:
        return str(value or "").strip().upper()

    @field_validator("event_id", "home_team", "away_team", mode="before")
    @classmethod
    def strip_required_text(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator(
        "provider_event_id",
        "provider_market_id",
        "market_type",
        "selection",
        "book",
        "provider",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: Any) -> str | None:
        return _optional_text(value)

    @field_validator("event_time", "as_of", "event_started_at", "quote_captured_at")
    @classmethod
    def require_timezone(cls, value: datetime | None, info):
        return _aware(value, info.field_name) if value is not None else None

    @field_validator("market_home_probability")
    @classmethod
    def probability_range(cls, value: float | None) -> float | None:
        if value is not None and not 0.0 < value < 1.0:
            raise ValueError("market_home_probability must be strictly between 0 and 1")
        return value

    @field_validator("line", "american_price")
    @classmethod
    def finite_market_number(cls, value: float | None, info) -> float | None:
        if value is not None and not math.isfinite(float(value)):
            raise ValueError(f"{info.field_name} must be finite")
        return value

    @field_validator("raw_snapshot_sha256")
    @classmethod
    def valid_raw_sha(cls, value: str | None) -> str | None:
        if value is None:
            return None
        digest = value.strip().lower()
        if not SHA256_RE.fullmatch(digest):
            raise ValueError("raw_snapshot_sha256 must be lowercase SHA-256")
        return digest

    @model_validator(mode="after")
    def chronology_and_teams(self):
        start = self.event_started_at or self.event_time
        captured = self.quote_captured_at or self.as_of
        if not self.as_of < self.event_time:
            raise ValueError("pregame chronology requires as_of < event_time")
        if not captured < start:
            raise ValueError("market chronology requires quote_captured_at < event_started_at/event_time")
        if self.home_team.casefold() == self.away_team.casefold():
            raise ValueError("home_team and away_team must differ")
        return self


class CanonicalTrainingRow(PregameSnapshot):
    target_home_win: int
    label_available_at: datetime
    event_ended_at: datetime | None = None
    settlement_observed_at: datetime | None = None
    settlement_source: str | None = None
    settlement_source_event_id: str | None = None
    final_home_score: float | None = None
    final_away_score: float | None = None
    settlement_status: str | None = None
    settlement_payload_sha256: str | None = None

    @field_validator("target_home_win")
    @classmethod
    def binary_target(cls, value: int) -> int:
        if value not in (0, 1):
            raise ValueError("target_home_win must be 0 or 1")
        return value

    @field_validator("label_available_at", "event_ended_at", "settlement_observed_at")
    @classmethod
    def settlement_time_timezone(cls, value: datetime | None, info) -> datetime | None:
        return _aware(value, info.field_name) if value is not None else None

    @field_validator("settlement_source", "settlement_source_event_id", "settlement_status", mode="before")
    @classmethod
    def normalize_settlement_text(cls, value: Any) -> str | None:
        return _optional_text(value)

    @field_validator("final_home_score", "final_away_score")
    @classmethod
    def finite_score(cls, value: float | None, info) -> float | None:
        if value is not None and not math.isfinite(float(value)):
            raise ValueError(f"{info.field_name} must be finite")
        return value

    @field_validator("settlement_payload_sha256")
    @classmethod
    def valid_settlement_sha(cls, value: str | None) -> str | None:
        if value is None:
            return None
        digest = value.strip().lower()
        if not SHA256_RE.fullmatch(digest):
            raise ValueError("settlement_payload_sha256 must be lowercase SHA-256")
        return digest

    @model_validator(mode="after")
    def settlement_chronology(self):
        start = self.event_started_at or self.event_time
        if not self.label_available_at > start:
            raise ValueError("label_available_at must be after event start")
        if self.event_ended_at is not None:
            if not self.event_ended_at > start:
                raise ValueError("event_ended_at must be after event start")
            if self.label_available_at < self.event_ended_at:
                raise ValueError("label_available_at cannot precede event_ended_at")
        if self.settlement_observed_at is not None:
            lower = self.event_ended_at or start
            if self.settlement_observed_at <= lower:
                raise ValueError("settlement_observed_at must be after the event/end boundary")
        if (self.final_home_score is None) ^ (self.final_away_score is None):
            raise ValueError("final scores must be supplied together")
        if self.final_home_score is not None and self.final_away_score is not None:
            if self.final_home_score == self.final_away_score:
                raise ValueError("canonical binary home-win rows cannot settle to a tie")
            derived = int(self.final_home_score > self.final_away_score)
            if derived != self.target_home_win:
                raise ValueError("final scores disagree with target_home_win")
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
        errors.append({"row": None, "error": f"duplicate sport/event_id keys: {sorted(set(duplicate_keys))[:20]}"})
    if errors:
        raise ValueError(json.dumps({"contract_version": CONTRACT_VERSION, "errors": errors[:50]}, indent=2, sort_keys=True))

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
    parser = argparse.ArgumentParser(description="Validate PhilthyParleys sports data against a fail-closed contract")
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
        args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
