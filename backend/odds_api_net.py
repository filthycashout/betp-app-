from __future__ import annotations

import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date as date_cls, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SPORT_QUERY: dict[str, tuple[str, str]] = {
    "NFL": ("american-football", "NFL"),
    "NBA": ("basketball", "NBA"),
    "MLB": ("baseball", "MLB"),
    "NHL": ("ice-hockey", "NHL"),
}
PACIFIC = ZoneInfo("America/Los_Angeles")
DEFAULT_BASE_URL = "https://api.odds-api.net/v1"


def configured() -> bool:
    key = os.getenv("ODDS_API_NET_KEY", "").strip()
    rotated = os.getenv("CREDENTIAL_ROTATION_CONFIRMED", "").strip().lower() == "true"
    return bool(key and rotated)


def status() -> dict[str, Any]:
    return {
        "provider": "odds-api.net",
        "configured": configured(),
        "credential_env": "ODDS_API_NET_KEY",
        "base_url": os.getenv("ODDS_API_NET_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        "sports": list(SPORT_QUERY),
        "bookmakers": [
            item.strip()
            for item in os.getenv("ODDS_API_NET_BOOKMAKERS", "fanduel,draftkings,pinnacle,betmgm,caesars").split(",")
            if item.strip()
        ],
    }


def _session() -> requests.Session:
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=0.35,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"Accept": "application/json"})
    return session


def _request(path: str, *, params: dict[str, Any] | None = None, timeout: float = 10.0) -> dict[str, Any]:
    if not configured():
        raise RuntimeError("odds-api.net provider is not configured with a rotated server-side key")
    base = os.getenv("ODDS_API_NET_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    key = os.environ["ODDS_API_NET_KEY"].strip()
    response = _session().get(
        f"{base}/{path.lstrip('/')}",
        params=params or {},
        headers={"X-API-Key": key},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("odds-api.net returned a non-object payload")
    return payload


def _event_id(row: dict[str, Any]) -> str:
    return str(row.get("event_id") or row.get("gameID") or row.get("id") or "").strip()


def _to_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            return None
        if number > 10_000_000_000:
            number /= 1000.0
        try:
            return datetime.fromtimestamp(number, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: Any) -> str | None:
    parsed = _to_datetime(value)
    return parsed.isoformat().replace("+00:00", "Z") if parsed else None


def _decimal_to_american(value: Any) -> float | None:
    try:
        decimal = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(decimal) or decimal <= 1.0:
        return None
    if decimal >= 2.0:
        return round((decimal - 1.0) * 100.0, 3)
    return round(-100.0 / (decimal - 1.0), 3)


def _market_kind(row: dict[str, Any]) -> str | None:
    raw = " ".join(
        str(row.get(key) or "")
        for key in ("market_key", "type", "bet_type", "metric")
    ).lower().replace("_", " ").replace("-", " ")
    if any(token in raw for token in ("moneyline", "money line", "h2h", "match winner")):
        return "h2h"
    if any(token in raw for token in ("spread", "handicap")):
        return "spreads"
    if any(token in raw for token in ("total", "over under", "over/under")) and not row.get("player_name"):
        return "totals"
    return None


def _side(row: dict[str, Any]) -> str:
    values = [row.get("side"), row.get("selection_name"), row.get("selection_key")]
    text = " ".join(str(value or "") for value in values).lower().replace("_", " ").replace(":", " ")
    if "home" in text:
        return "home"
    if "away" in text:
        return "away"
    if "over" in text:
        return "over"
    if "under" in text:
        return "under"
    return ""


def _line_number(row: dict[str, Any]) -> float | None:
    raw = row.get("line")
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _complete_market(kind: str, outcomes: list[dict[str, Any]]) -> bool:
    names = {str(item.get("name") or "").lower() for item in outcomes}
    if kind in {"h2h", "spreads"}:
        return len(outcomes) >= 2 and len(names) >= 2
    if kind == "totals":
        return "over" in names and "under" in names
    return False


def normalize_event(event: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any] | None:
    event_id = _event_id(event)
    home = str(event.get("home_team") or event.get("home") or "").strip()
    away = str(event.get("away_team") or event.get("away") or "").strip()
    start = _to_datetime(event.get("start_time") or event.get("commence_time") or event.get("start"))
    if not event_id or not home or not away or start is None:
        return None

    snapshot_time = _iso(snapshot.get("as_of_ts_ms") or event.get("last_capture"))
    items = snapshot.get("items") or []
    if not isinstance(items, list):
        return None

    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in items:
        if not isinstance(row, dict) or row.get("is_available") is False:
            continue
        try:
            period = int(row.get("period") or 0)
        except (TypeError, ValueError):
            period = 0
        if period not in (0,):
            continue
        kind = _market_kind(row)
        if kind is None or row.get("player_name"):
            continue
        bookmaker = str(row.get("bookmaker") or "").strip()
        if not bookmaker:
            continue
        american = _decimal_to_american(row.get("odds"))
        if american is None:
            continue
        side = _side(row)
        line = _line_number(row)
        if kind == "h2h":
            if side == "home":
                name = home
            elif side == "away":
                name = away
            else:
                selection = str(row.get("selection_name") or "").strip()
                if selection not in {home, away}:
                    continue
                name = selection
            group_id = str(row.get("market_group_id") or row.get("market_key") or "h2h")
            outcome = {"name": name, "price": american}
        elif kind == "spreads":
            if side not in {"home", "away"} or line is None:
                continue
            name = home if side == "home" else away
            group_id = str(row.get("market_group_id") or f"spread:{abs(line):g}")
            outcome = {"name": name, "price": american, "point": line}
        else:
            if side not in {"over", "under"} or line is None:
                continue
            name = "Over" if side == "over" else "Under"
            group_id = str(row.get("market_group_id") or f"total:{line:g}")
            outcome = {"name": name, "price": american, "point": line}

        key = (bookmaker, kind, group_id)
        group = grouped.setdefault(
            key,
            {
                "bookmaker": bookmaker,
                "kind": kind,
                "group_id": group_id,
                "market_key": str(row.get("market_key") or ""),
                "outcomes": [],
            },
        )
        group["outcomes"].append(outcome)

    by_book: dict[str, list[dict[str, Any]]] = {}
    for group in grouped.values():
        if not _complete_market(group["kind"], group["outcomes"]):
            continue
        by_book.setdefault(group["bookmaker"], []).append(group)

    bookmakers: list[dict[str, Any]] = []
    for bookmaker, groups in by_book.items():
        markets: list[dict[str, Any]] = []
        for kind in ("h2h", "spreads", "totals"):
            candidates = [group for group in groups if group["kind"] == kind]
            if not candidates:
                continue
            candidates.sort(
                key=lambda group: (
                    "alternate" in group["market_key"].lower() or "alt" in group["market_key"].lower(),
                    group["group_id"],
                )
            )
            selected = candidates[0]
            markets.append({"key": kind, "outcomes": selected["outcomes"]})
        if markets:
            bookmakers.append(
                {
                    "key": bookmaker.lower().replace(" ", "_"),
                    "title": bookmaker,
                    "last_update": snapshot_time,
                    "markets": markets,
                }
            )

    if not bookmakers:
        return None
    return {
        "id": event_id,
        "home_team": home,
        "away_team": away,
        "commence_time": start.isoformat().replace("+00:00", "Z"),
        "bookmakers": bookmakers,
        "data_quality": "PREGAME_CREDENTIALLED",
        "market_source": "ODDS_API_NET",
        "provider_as_of": snapshot_time,
    }


def events_for_date(sport: str, target_date: date_cls) -> list[dict[str, Any]]:
    sport = sport.upper()
    if sport not in SPORT_QUERY:
        raise ValueError(f"unsupported sport: {sport}")
    if not configured():
        return []

    sport_name, league = SPORT_QUERY[sport]
    event_payload = _request("/events", params={"sport": sport_name, "league": league, "limit": 100})
    rows = event_payload.get("items") or []
    if not isinstance(rows, list):
        return []

    events: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        start = _to_datetime(row.get("start_time"))
        if start is None or start.astimezone(PACIFIC).date() != target_date:
            continue
        if not _event_id(row):
            continue
        events.append(row)

    bookmakers = os.getenv("ODDS_API_NET_BOOKMAKERS", "fanduel,draftkings,pinnacle,betmgm,caesars").strip()

    def fetch_one(event: dict[str, Any]) -> dict[str, Any] | None:
        params: dict[str, Any] = {}
        if bookmakers:
            params["bookmakers"] = bookmakers
        snapshot = _request(f"/events/{_event_id(event)}/odds/snapshot", params=params)
        return normalize_event(event, snapshot)

    normalized: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(events)))) as pool:
        future_map = {pool.submit(fetch_one, event): event for event in events}
        for future in as_completed(future_map):
            try:
                item = future.result()
            except Exception:
                item = None
            if item is not None:
                normalized.append(item)

    normalized.sort(key=lambda row: str(row.get("commence_time") or ""))
    return normalized
