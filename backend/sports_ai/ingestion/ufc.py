"""Fail-closed UFC/MMA event adapter for The Odds API v4.

UFC is event-driven rather than a daily league schedule. This adapter normalizes
fight-winner markets into the shared sports-AI contract while deliberately
leaving unavailable props, timestamps, and sharp-anchor evidence unavailable.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
from threading import Lock
from time import monotonic
from typing import Any
from zoneinfo import ZoneInfo

UFC_SPORT_KEY = "mma_mixed_martial_arts"
UFC_ODDS_URL = f"https://api.the-odds-api.com/v4/sports/{UFC_SPORT_KEY}/odds/"
PACIFIC = ZoneInfo("America/Los_Angeles")
EVENT_CACHE_TTL_SECONDS = 60
_EVENT_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_EVENT_CACHE_LOCK = Lock()


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_ufc_events(
    payload: object,
    *,
    target_date: date | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Validate upcoming fight events without inventing missing market data."""
    if not isinstance(payload, list):
        return []

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in payload:
        if not isinstance(row, dict):
            continue
        supplied_key = row.get("sport_key")
        if supplied_key and supplied_key != UFC_SPORT_KEY:
            continue

        event_id = str(row.get("id") or "").strip()
        fighter_a = str(row.get("home_team") or "").strip()
        fighter_b = str(row.get("away_team") or "").strip()
        event_time = _utc(row.get("commence_time"))
        if not event_id or event_id in seen or not fighter_a or not fighter_b:
            continue
        if fighter_a.casefold() == fighter_b.casefold() or event_time is None:
            continue
        if event_time <= current:
            continue
        if target_date is not None and event_time.astimezone(PACIFIC).date() != target_date:
            continue

        seen.add(event_id)
        normalized.append({
            "id": event_id,
            "event_id": event_id,
            "sport": "UFC",
            "sport_key": UFC_SPORT_KEY,
            "sport_title": str(row.get("sport_title") or "MMA"),
            "home": fighter_a,
            "away": fighter_b,
            "home_team": fighter_a,
            "away_team": fighter_b,
            "event_time": event_time.isoformat(),
            "commence_time": event_time.isoformat().replace("+00:00", "Z"),
            "bookmakers": row.get("bookmakers") if isinstance(row.get("bookmakers"), list) else [],
            "market_source": "THE_ODDS_API_V4_UFC",
            "market_scope": "fight_winner_moneyline",
            "player_props_supported": False,
        })

    return sorted(normalized, key=lambda item: item["event_time"])


def fetch_ufc_events(
    runtime: Any,
    target_date: date,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Fetch UFC odds only when the existing credential-rotation gate permits it."""
    # Check credential rotation on every request, even when the event feed is cached.
    key = runtime._odds_key()
    cache_key = target_date.isoformat()
    current_tick = monotonic()
    with _EVENT_CACHE_LOCK:
        cached = _EVENT_CACHE.get(cache_key)
        if cached and current_tick < cached[0]:
            return deepcopy(cached[1])
        _EVENT_CACHE.pop(cache_key, None)

    payload = runtime._json(
        UFC_ODDS_URL,
        params={
            "apiKey": key,
            "regions": "us",
            "markets": "h2h",
            "oddsFormat": "american",
            "dateFormat": "iso",
        },
        timeout=10,
    )
    if not isinstance(payload, list):
        raise ValueError("UFC provider returned an invalid event payload")
    rows = normalize_ufc_events(payload, target_date=target_date, now=now)
    with _EVENT_CACHE_LOCK:
        _EVENT_CACHE[cache_key] = (monotonic() + EVENT_CACHE_TTL_SECONDS, deepcopy(rows))
    return rows
