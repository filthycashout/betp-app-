from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "2"
SPORTS = {"NFL", "NBA", "MLB", "NHL"}
MARKETS = {"moneyline", "spread", "total", "player_prop"}
_HASH_EXCLUDED = {"record_sha256", "merkle_root", "merkle_leaf_index", "merkle_proof"}


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def sha256_hex(value: Any) -> str:
    payload = value if isinstance(value, (bytes, bytearray)) else canonical_json(value)
    return hashlib.sha256(payload).hexdigest()


def signal_hash_payload(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if k not in _HASH_EXCLUDED}


def signal_commitment(record: dict[str, Any]) -> str:
    return sha256_hex(signal_hash_payload(record))


def parse_utc(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def decimal_from_american(price: float | int) -> float:
    p = float(price)
    if p == 0:
        raise ValueError("American odds cannot be zero")
    return round(1.0 + (100.0 / -p if p < 0 else p / 100.0), 8)


def reason_codes_for(
    probability_source: str | None,
    *,
    promoted: bool,
    market_fresh: bool,
    external_agreement: bool | None = None,
) -> list[str]:
    source = str(probability_source or "").lower()
    reasons: list[str] = []
    if promoted:
        reasons.append("promoted_model")
    elif "market" in source or "consensus" in source:
        reasons.append("market_baseline")
    elif "form" in source or "record" in source:
        reasons.append("recent_form_fallback")
    else:
        reasons.append("probability_source_recorded")
    if market_fresh:
        reasons.append("fresh_market_quote")
    if external_agreement is True:
        reasons.append("external_model_agreement")
    elif external_agreement is False:
        reasons.append("external_model_disagreement")
    return list(dict.fromkeys(reasons))


def make_signal(
    *,
    match_id: str,
    league: str,
    season: str | int,
    home_team: str,
    away_team: str,
    snapshot_time_utc: Any,
    event_time_utc: Any,
    data_latency_ms: int,
    market_type: str,
    selection: str,
    line: float | None,
    odds_decimal: float,
    raw_probability: float | None,
    calibrated_probability: float | None,
    engine_version: str,
    model_family: str,
    reason_codes: Iterable[str],
    model_id: str | None = None,
    model_artifact_sha256: str | None = None,
    dataset_sha256: str | None = None,
    feature_schema_sha256: str | None = None,
    source: str | None = None,
    source_observed_at_utc: Any | None = None,
    signal_id: str | None = None,
) -> dict[str, Any]:
    sport = league.upper().strip()
    if sport not in SPORTS:
        raise ValueError(f"Unsupported league: {league}")
    if market_type not in MARKETS:
        raise ValueError(f"Unsupported market_type: {market_type}")
    snapshot = parse_utc(snapshot_time_utc)
    event_time = parse_utc(event_time_utc)
    if snapshot >= event_time:
        raise ValueError("Chronology violation: snapshot_time_utc must be before event_time_utc")
    if data_latency_ms < 0:
        raise ValueError("data_latency_ms must be non-negative")
    if not math.isfinite(float(odds_decimal)) or float(odds_decimal) <= 1.0:
        raise ValueError("odds_decimal must be finite and greater than 1")
    for name, value in (
        ("raw_probability", raw_probability),
        ("calibrated_probability", calibrated_probability),
    ):
        if value is not None and not 0.0 <= float(value) <= 1.0:
            raise ValueError(f"{name} must be between 0 and 1")

    observed = parse_utc(source_observed_at_utc).isoformat() if source_observed_at_utc else None
    if observed and parse_utc(observed) > snapshot:
        raise ValueError("Source observation occurs after prediction snapshot")

    record: dict[str, Any] = {
        "signal_id": signal_id or str(uuid.uuid4()),
        "match_id": str(match_id),
        "league": sport,
        "season": str(season),
        "home_team": str(home_team),
        "away_team": str(away_team),
        "timestamp_utc": snapshot.isoformat(),
        "snapshot_time_utc": snapshot.isoformat(),
        "event_time_utc": event_time.isoformat(),
        "data_latency_ms": int(data_latency_ms),
        "market_type": market_type,
        "selection": str(selection),
        "line": None if line is None else float(line),
        "odds_decimal": float(odds_decimal),
        "raw_probability": None if raw_probability is None else float(raw_probability),
        "calibrated_probability": (
            None if calibrated_probability is None else float(calibrated_probability)
        ),
        "engine_version": str(engine_version),
        "schema_version": SCHEMA_VERSION,
        "model_family": str(model_family),
        "model_id": model_id,
        "model_artifact_sha256": model_artifact_sha256,
        "dataset_sha256": dataset_sha256,
        "feature_schema_sha256": feature_schema_sha256,
        "reason_codes": list(dict.fromkeys(str(x) for x in reason_codes if str(x))),
        "source": source,
        "source_observed_at_utc": observed,
        "merkle_root": None,
        "merkle_leaf_index": None,
        "merkle_proof": [],
    }
    record["record_sha256"] = signal_commitment(record)
    return record


def verify_signal(record: dict[str, Any]) -> bool:
    expected = record.get("record_sha256")
    return isinstance(expected, str) and signal_commitment(record) == expected


def _pair_hash(left: str, right: str) -> str:
    return hashlib.sha256(bytes.fromhex(left) + bytes.fromhex(right)).hexdigest()


def merkle_root(leaves: list[str]) -> str | None:
    if not leaves:
        return None
    layer = list(leaves)
    while len(layer) > 1:
        if len(layer) % 2:
            layer.append(layer[-1])
        layer = [_pair_hash(layer[i], layer[i + 1]) for i in range(0, len(layer), 2)]
    return layer[0]


def merkle_proof(leaves: list[str], index: int) -> list[dict[str, str]]:
    if index < 0 or index >= len(leaves):
        raise IndexError("Merkle leaf index out of range")
    proof: list[dict[str, str]] = []
    layer = list(leaves)
    idx = index
    while len(layer) > 1:
        if len(layer) % 2:
            layer.append(layer[-1])
        sibling = idx - 1 if idx % 2 else idx + 1
        proof.append({
            "side": "left" if sibling < idx else "right",
            "sha256": layer[sibling],
        })
        layer = [_pair_hash(layer[i], layer[i + 1]) for i in range(0, len(layer), 2)]
        idx //= 2
    return proof


def verify_merkle_proof(leaf: str, proof: Iterable[dict[str, str]], root: str) -> bool:
    value = leaf
    for node in proof:
        side = node.get("side")
        sibling = node.get("sha256")
        if side == "left":
            value = _pair_hash(str(sibling), value)
        elif side == "right":
            value = _pair_hash(value, str(sibling))
        else:
            return False
    return value == root


def anchor_batch(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    leaves = [str(row["record_sha256"]) for row in records]
    root = merkle_root(leaves)
    if root is None:
        raise ValueError("Cannot anchor an empty signal batch")
    anchored: list[dict[str, Any]] = []
    for index, row in enumerate(records):
        item = dict(row)
        item["merkle_root"] = root
        item["merkle_leaf_index"] = index
        item["merkle_proof"] = merkle_proof(leaves, index)
        anchored.append(item)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "leaf_count": len(leaves),
        "merkle_root": root,
        "leaf_record_sha256": leaves,
    }
    manifest["manifest_sha256"] = sha256_hex(manifest)
    return anchored, manifest


def append_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
