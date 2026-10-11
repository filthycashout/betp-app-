from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from sports_ai import SUPPORTED_SPORTS
from sports_ai.betting.clv import price_clv, probability_clv
from sports_ai.core.db import DatabaseUnavailable, get_engine
from sports_ai.core.models import Base, ClosingSnapshotRow, RecommendationRow


def _utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _probability(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} is required") from exc
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"{field} must be in [0, 1]")
    return result


def build_recommendation_record(
    result: dict[str, Any],
    *,
    as_of: datetime | str,
    event_time: datetime | str,
) -> dict[str, Any]:
    as_of_dt = _utc(as_of)
    event_dt = _utc(event_time)
    if not as_of_dt < event_dt:
        raise ValueError("recommendation must be recorded before event_time")

    sport = str(result.get("sport") or "").upper()
    if sport not in SUPPORTED_SPORTS:
        raise ValueError("unsupported sport")
    event_id = str(result.get("event_id") or "").strip()
    selection = str(result.get("selection") or "").strip()
    market = str(result.get("market") or "").strip()
    if not event_id or not selection or not market:
        raise ValueError("event_id, market, and selection are required")

    decision = result.get("decision") or {}
    offered = float(result["soft_american_odds"])
    if offered == 0.0 or abs(offered) < 100.0:
        raise ValueError("soft_american_odds must be valid American odds")
    record = {
        "schema_version": "1",
        "sport": sport,
        "event_id": event_id,
        "market": market,
        "selection": selection,
        "line": result.get("line"),
        "offered_american": offered,
        "fair_probability": _probability(result.get("final_probability"), "final_probability"),
        "market_anchor_probability": _probability(
            result.get("market_anchor_probability"),
            "market_anchor_probability",
        ),
        "model_probability": (
            None
            if result.get("model_probability") is None
            else _probability(result.get("model_probability"), "model_probability")
        ),
        "edge": float(result.get("edge") or 0.0),
        "expected_value": float(decision.get("ev") or 0.0),
        "eligible": bool(decision.get("eligible")),
        "probability_source": str(result.get("probability_source") or "UNKNOWN"),
        "as_of_utc": _iso(as_of_dt),
        "event_time_utc": _iso(event_dt),
        "decision_reasons": list(decision.get("reasons") or []),
        "sharp_anchor_verified": bool(result.get("sharp_anchor_verified")),
        "market_anchor_kind": str(result.get("market_anchor_kind") or ""),
    }
    record["recommendation_id"] = _digest(record)
    return record


def _ensure_schema() -> Any:
    try:
        engine = get_engine()
        Base.metadata.create_all(
            engine,
            tables=[RecommendationRow.__table__, ClosingSnapshotRow.__table__],
        )
        return engine
    except DatabaseUnavailable:
        raise
    except Exception as exc:
        raise DatabaseUnavailable("sports_ai PostgreSQL schema is unavailable") from exc


def store_recommendation_record(record: dict[str, Any]) -> dict[str, Any]:
    try:
        engine = _ensure_schema()
    except DatabaseUnavailable:
        return {"stored": False, "status": "DATABASE_UNAVAILABLE", "recommendation_id": record.get("recommendation_id")}
    values = {
        "recommendation_id": record["recommendation_id"],
        "sport": record["sport"],
        "event_id": record["event_id"],
        "market": record["market"],
        "selection": record["selection"],
        "line": record.get("line"),
        "offered_american": record["offered_american"],
        "fair_probability": record["fair_probability"],
        "market_anchor_probability": record["market_anchor_probability"],
        "model_probability": record.get("model_probability"),
        "edge": record["edge"],
        "expected_value": record["expected_value"],
        "eligible": record["eligible"],
        "probability_source": record["probability_source"],
        "as_of": _utc(record["as_of_utc"]),
        "event_time": _utc(record["event_time_utc"]),
        "payload": record,
    }
    try:
        with engine.begin() as conn:
            conn.execute(
                insert(RecommendationRow.__table__)
                .values(**values)
                .on_conflict_do_nothing(index_elements=[RecommendationRow.recommendation_id])
            )
        return {"stored": True, "status": "OK", "recommendation_id": record["recommendation_id"]}
    except Exception:
        return {"stored": False, "status": "DATABASE_WRITE_FAILED", "recommendation_id": record.get("recommendation_id")}


def build_closing_record(
    *,
    recommendation_id: str,
    close_american: float,
    observed_at: datetime | str,
    event_time: datetime | str,
    close_fair_probability: float | None = None,
) -> dict[str, Any]:
    observed = _utc(observed_at)
    event = _utc(event_time)
    if observed > event:
        raise ValueError("closing snapshot must not be observed after event_time")
    price = float(close_american)
    if price == 0.0 or abs(price) < 100.0:
        raise ValueError("close_american must be valid American odds")
    fair = None if close_fair_probability is None else _probability(close_fair_probability, "close_fair_probability")
    core = {
        "schema_version": "1",
        "recommendation_id": str(recommendation_id),
        "close_american": price,
        "close_fair_probability": fair,
        "observed_at_utc": _iso(observed),
        "event_time_utc": _iso(event),
    }
    core["record_sha256"] = _digest(core)
    return core


def store_closing_record(record: dict[str, Any]) -> dict[str, Any]:
    try:
        engine = _ensure_schema()
    except DatabaseUnavailable:
        return {"stored": False, "status": "DATABASE_UNAVAILABLE", "record_sha256": record.get("record_sha256")}
    values = {
        "record_sha256": record["record_sha256"],
        "recommendation_id": record["recommendation_id"],
        "observed_at": _utc(record["observed_at_utc"]),
        "event_time": _utc(record["event_time_utc"]),
        "close_american": record["close_american"],
        "close_fair_probability": record.get("close_fair_probability"),
        "payload": record,
    }
    try:
        with engine.begin() as conn:
            conn.execute(
                insert(ClosingSnapshotRow.__table__)
                .values(**values)
                .on_conflict_do_nothing(index_elements=[ClosingSnapshotRow.record_sha256])
            )
        return {"stored": True, "status": "OK", "record_sha256": record["record_sha256"]}
    except Exception:
        return {"stored": False, "status": "DATABASE_WRITE_FAILED", "record_sha256": record.get("record_sha256")}


def clv_report(recommendation_id: str) -> dict[str, Any]:
    try:
        engine = _ensure_schema()
    except DatabaseUnavailable:
        return {"status": "DATABASE_UNAVAILABLE", "recommendation_id": recommendation_id}
    try:
        with Session(engine) as session:
            recommendation = session.scalars(
                select(RecommendationRow).where(RecommendationRow.recommendation_id == recommendation_id)
            ).first()
            closing = session.scalars(
                select(ClosingSnapshotRow)
                .where(ClosingSnapshotRow.recommendation_id == recommendation_id)
                .order_by(ClosingSnapshotRow.observed_at.desc())
                .limit(1)
            ).first()
        if recommendation is None:
            return {"status": "RECOMMENDATION_NOT_FOUND", "recommendation_id": recommendation_id}
        if closing is None:
            return {"status": "CLOSE_NOT_RECORDED", "recommendation_id": recommendation_id}
        prob_clv = None
        if closing.close_fair_probability is not None:
            prob_clv = probability_clv(recommendation.fair_probability, closing.close_fair_probability)
        return {
            "status": "OK",
            "recommendation_id": recommendation_id,
            "price_clv": price_clv(recommendation.offered_american, closing.close_american),
            "probability_clv": prob_clv,
            "offered_american": recommendation.offered_american,
            "close_american": closing.close_american,
            "fair_probability_at_recommendation": recommendation.fair_probability,
            "closing_fair_probability": closing.close_fair_probability,
            "closing_observed_at": closing.observed_at.isoformat(),
        }
    except Exception:
        return {"status": "DATABASE_READ_FAILED", "recommendation_id": recommendation_id}
