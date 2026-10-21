"""Fail-closed canonical contracts for future UFC provider integrations.

This module intentionally does not fetch data or claim live provider support.
It normalizes already-fetched, authorized source records for deterministic tests.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def normalize_event(
    raw: dict[str, Any],
    *,
    provider: str,
    fetched_at: str,
    require_future: bool = True,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Normalize one source event; return None when required evidence is invalid."""
    if not isinstance(raw, dict) or not provider.strip():
        return None

    event_id = str(raw.get("event_id") or raw.get("id") or "").strip()
    fighter_a = str(raw.get("fighter_a") or raw.get("home") or "").strip()
    fighter_b = str(raw.get("fighter_b") or raw.get("away") or "").strip()
    if not event_id or not fighter_a or not fighter_b:
        return None
    if fighter_a.casefold() == fighter_b.casefold():
        return None

    start = _timestamp(raw.get("start_time") or raw.get("commence_time"))
    fetched = _timestamp(fetched_at)
    if start is None or fetched is None:
        return None
    clock = now.astimezone(timezone.utc) if now and now.tzinfo else now
    clock = clock or datetime.now(timezone.utc)
    if require_future and start <= clock:
        return None

    weight_class = str(raw.get("weight_class") or "").strip() or None
    round_count = raw.get("scheduled_rounds")
    if round_count is not None:
        if isinstance(round_count, bool) or not isinstance(round_count, int) or round_count <= 0:
            return None

    return {
        "sport": "UFC",
        "provider": provider.strip(),
        "source_event_id": event_id,
        "event_id": f"UFC:{event_id}",
        "event_time_utc": start.isoformat().replace("+00:00", "Z"),
        "fetched_at_utc": fetched.isoformat().replace("+00:00", "Z"),
        "fighter_a": fighter_a,
        "fighter_b": fighter_b,
        "weight_class": weight_class,
        "scheduled_rounds": round_count,
        "evidence_status": "NORMALIZED_UNVERIFIED_PROVIDER",
        "promotion_eligible": False,
    }


def normalize_market(
    raw: dict[str, Any],
    *,
    provider: str,
    source_event_id: str,
    fetched_at: str,
) -> dict[str, Any] | None:
    """Normalize one two-way UFC market while retaining quote provenance."""
    if not isinstance(raw, dict) or not provider.strip() or not source_event_id.strip():
        return None

    market_id = str(raw.get("market_id") or raw.get("key") or "").strip()
    selection = str(raw.get("selection") or raw.get("outcome") or "").strip()
    quote_at = _timestamp(raw.get("quoted_at") or raw.get("last_update"))
    fetched = _timestamp(fetched_at)
    try:
        price = float(raw.get("american_price"))
    except (TypeError, ValueError):
        return None
    if not market_id or not selection or quote_at is None or fetched is None:
        return None
    if not math.isfinite(price) or price == 0 or abs(price) > 100000:
        return None

    line = raw.get("line")
    if line is not None:
        try:
            line = float(line)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(line):
            return None

    return {
        "sport": "UFC",
        "provider": provider.strip(),
        "source_event_id": source_event_id.strip(),
        "market_id": market_id,
        "selection": selection,
        "american_price": price,
        "line": line,
        "quoted_at_utc": quote_at.isoformat().replace("+00:00", "Z"),
        "fetched_at_utc": fetched.isoformat().replace("+00:00", "Z"),
        "evidence_status": "NORMALIZED_UNVERIFIED_PROVIDER",
        "promotion_eligible": False,
    }


def provider_status(*, configured: bool = False, canary_verified: bool = False) -> dict[str, Any]:
    """Never infer availability from configuration alone."""
    verified = configured is True and canary_verified is True
    return {
        "sport": "UFC",
        "status": "VERIFIED" if verified else "UNAVAILABLE",
        "configured": configured is True,
        "canary_verified": canary_verified is True,
        "live_picks_enabled": False,
        "model_promotion_enabled": False,
        "reason": (
            "Provider verification recorded; live picks remain disabled pending "
            "canonical evidence and model/recommendation gates."
            if verified
            else "No verified UFC provider adapter and canary evidence."
        ),
    }
