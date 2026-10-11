from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sports_ai.betting.prices import implied_prob


def _utc(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _norm(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _same_team(a: Any, b: Any) -> bool:
    left, right = _norm(a), _norm(b)
    return bool(left and right and (left == right or left in right or right in left))


def _american(value: Any) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if price == 0.0 or abs(price) < 100.0:
        return None
    return price


def _same_event(game: dict[str, Any], event: dict[str, Any]) -> bool:
    game_time = _utc(game.get("event_time") or game.get("commence_time"))
    event_time = _utc(event.get("commence_time") or event.get("event_time"))
    if game_time is None or event_time is None:
        return False
    if abs((game_time - event_time).total_seconds()) > 30 * 60:
        return False
    return (
        _same_team(game.get("home") or game.get("home_team"), event.get("home_team") or event.get("home"))
        and _same_team(game.get("away") or game.get("away_team"), event.get("away_team") or event.get("away"))
    )


def extract_sharp_moneyline_anchor(
    events: Iterable[dict[str, Any]],
    *,
    game: dict[str, Any],
    selection: str,
    allowed_book_keys: Iterable[str] = ("pinnacle",),
    now: datetime | None = None,
    max_age_seconds: int = 180,
) -> dict[str, Any]:
    """Extract a provider-timestamped, same-book, two-way no-vig sharp anchor.

    Fetch-observed timestamps are intentionally insufficient here. A quote only
    qualifies when the bookmaker/market supplies its own update timestamp.
    """

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    allowed = [_norm(key) for key in allowed_book_keys if _norm(key)]
    if not allowed:
        return {"status": "SHARP_BOOK_ALLOWLIST_EMPTY", "verified": False, "anchor": None}

    home = str(game.get("home") or game.get("home_team") or "").strip()
    away = str(game.get("away") or game.get("away_team") or "").strip()
    if not home or not away:
        return {"status": "TEAM_IDENTITY_UNAVAILABLE", "verified": False, "anchor": None}
    if _same_team(selection, home):
        canonical_selection = home
        opposite = away
    elif _same_team(selection, away):
        canonical_selection = away
        opposite = home
    else:
        return {"status": "SHARP_SELECTION_UNMATCHED", "verified": False, "anchor": None}

    candidates: list[tuple[int, datetime, dict[str, Any]]] = []
    matched_event = False
    matched_book = False
    provider_timestamp_seen = False
    stale_seen = False

    for event in events:
        if not isinstance(event, dict) or not _same_event(game, event):
            continue
        matched_event = True
        event_time = _utc(event.get("commence_time") or event.get("event_time"))
        if event_time is None or event_time <= current:
            continue
        provider = str(event.get("market_source") or event.get("provider") or "unknown")
        for book in event.get("bookmakers") or []:
            if not isinstance(book, dict):
                continue
            book_key = str(book.get("key") or "").strip()
            book_title = str(book.get("title") or book_key or "").strip()
            identities = {_norm(book_key), _norm(book_title)}
            ranks = [allowed.index(identity) for identity in identities if identity in allowed]
            if not ranks:
                continue
            matched_book = True
            rank = min(ranks)
            for market in book.get("markets") or []:
                if not isinstance(market, dict) or market.get("key") != "h2h":
                    continue
                updated = _utc(market.get("last_update") or book.get("last_update"))
                if updated is None:
                    continue
                provider_timestamp_seen = True
                age = (current - updated).total_seconds()
                if not -30.0 <= age <= float(max_age_seconds):
                    stale_seen = True
                    continue
                if updated >= event_time:
                    continue

                outcomes = market.get("outcomes") or []
                if len(outcomes) != 2:
                    continue
                selected = next(
                    (row for row in outcomes if isinstance(row, dict) and _same_team(row.get("name"), canonical_selection)),
                    None,
                )
                other = next(
                    (row for row in outcomes if isinstance(row, dict) and _same_team(row.get("name"), opposite)),
                    None,
                )
                if selected is None or other is None:
                    continue
                selected_price = _american(selected.get("price"))
                other_price = _american(other.get("price"))
                if selected_price is None or other_price is None:
                    continue
                selected_implied = implied_prob(selected_price)
                other_implied = implied_prob(other_price)
                total = selected_implied + other_implied
                if total <= 0.0:
                    continue

                source = book_key or book_title
                anchor = {
                    "source": source,
                    "book_key": book_key or source,
                    "book_title": book_title or source,
                    "provider": provider,
                    "provider_event_id": str(event.get("id") or ""),
                    "selection": canonical_selection,
                    "probability": selected_implied / total,
                    "no_vig": True,
                    "observed_at": updated.isoformat(),
                    "timestamp_basis": "provider_timestamp",
                    "raw_american_price": selected_price,
                    "opposite_american_price": other_price,
                }
                candidates.append((rank, updated, anchor))

    if candidates:
        candidates.sort(key=lambda row: (row[0], -row[1].timestamp()))
        anchor = candidates[0][2]
        return {"status": "VERIFIED", "verified": True, "anchor": anchor}
    if not matched_event:
        status = "SHARP_EVENT_NOT_MATCHED"
    elif not matched_book:
        status = "SHARP_BOOK_NOT_PRESENT"
    elif not provider_timestamp_seen:
        status = "SHARP_PROVIDER_TIMESTAMP_REQUIRED"
    elif stale_seen:
        status = "SHARP_QUOTE_STALE"
    else:
        status = "SHARP_TWO_SIDED_MARKET_INVALID"
    return {"status": status, "verified": False, "anchor": None}


def fetch_pinnacle_moneyline_anchor(
    runtime: Any,
    *,
    sport: str,
    game: dict[str, Any],
    selection: str,
    now: datetime | None = None,
    max_age_seconds: int = 180,
) -> dict[str, Any]:
    """Fetch Pinnacle H2H through the existing credential-governed Odds API client path.

    No credential is returned in the result. If rotation/key requirements are
    not satisfied, the function fails closed with a status instead of falling
    back to an unverified bookmaker.
    """

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    event_time = _utc(game.get("event_time") or game.get("commence_time"))
    if event_time is None or event_time <= current:
        return {"status": "NO_VERIFIED_PREGAME_EVENT", "verified": False, "anchor": None}
    try:
        api_key = runtime._odds_key()
        sport_key = runtime.SPORT_KEYS[sport.upper()]
    except Exception as exc:
        return {
            "status": "SHARP_CREDENTIAL_UNAVAILABLE",
            "verified": False,
            "anchor": None,
            "error_type": type(exc).__name__,
        }

    params = {
        "apiKey": api_key,
        "bookmakers": "pinnacle",
        "markets": "h2h",
        "oddsFormat": "american",
        "dateFormat": "iso",
        "commenceTimeFrom": (event_time - timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
        "commenceTimeTo": (event_time + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
    }
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
    try:
        call = lambda: runtime._json(url, params=params, timeout=12)
        payload = runtime._timed(f"{sport.upper()}.odds.pinnacle_sharp", call) if hasattr(runtime, "_timed") else call()
    except Exception as exc:
        return {
            "status": "SHARP_PROVIDER_UNAVAILABLE",
            "verified": False,
            "anchor": None,
            "error_type": type(exc).__name__,
        }
    if not isinstance(payload, list):
        return {"status": "SHARP_PROVIDER_INVALID_RESPONSE", "verified": False, "anchor": None}

    result = extract_sharp_moneyline_anchor(
        payload,
        game=game,
        selection=selection,
        allowed_book_keys=("pinnacle",),
        now=current,
        max_age_seconds=max_age_seconds,
    )
    result["retrieval"] = "the_odds_api_v4_bookmakers_pinnacle"
    if result.get("verified"):
        result["provenance_note"] = (
            "Pinnacle bookmaker identity and provider timestamp were verified in the upstream response; "
            "recommendation freshness still uses the configured maximum age."
        )
    return result
