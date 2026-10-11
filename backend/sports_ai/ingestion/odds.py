from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean
from typing import Any

from market_validation import MAX_QUOTE_AGE_SECONDS, implied, number, utc_time


def moneyline_snapshot_from_event(
    event: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    max_quote_age_seconds: int = MAX_QUOTE_AGE_SECONDS,
) -> dict[str, Any]:
    """Return a side-complete, point-in-time H2H snapshot.

    Only fresh two-sided prices from the same bookmaker contribute to the
    no-vig consensus. Best prices are retained independently for home and away,
    so a model is never forced to reuse the consensus-picked side's price.
    """

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    base: dict[str, Any] = {
        "status": "NO_FRESH_TWO_SIDED_MONEYLINE",
        "freshness_verified": False,
        "provider_timestamp_verified": False,
        "observed_at_verified": False,
        "freshness_basis": [],
        "home_team": None,
        "away_team": None,
        "home_probability": None,
        "away_probability": None,
        "home_best_price": None,
        "home_best_book": None,
        "home_best_price_last_update": None,
        "away_best_price": None,
        "away_best_book": None,
        "away_best_price_last_update": None,
        "last_update": None,
        "book_count": 0,
        "books_used": [],
    }
    if not event:
        return base

    start = utc_time(event.get("commence_time") or event.get("event_time"))
    if start is None or start <= current:
        return {**base, "status": "NO_VERIFIED_PREGAME_EVENT"}

    home = str(event.get("home_team") or event.get("home") or "").strip()
    away = str(event.get("away_team") or event.get("away") or "").strip()
    if not home or not away:
        return {**base, "status": "TEAM_IDENTITY_UNAVAILABLE"}

    pairs: list[dict[str, Any]] = []
    timestamp_bases: set[str] = set()
    for book in event.get("bookmakers") or []:
        if not isinstance(book, dict):
            continue
        book_name = str(book.get("key") or book.get("title") or "unknown")
        for market in book.get("markets") or []:
            if not isinstance(market, dict) or market.get("key") != "h2h":
                continue

            provider_updated = utc_time(market.get("last_update") or book.get("last_update"))
            observed = utc_time(market.get("observed_at") or book.get("observed_at"))
            updated = provider_updated or observed
            if updated is None:
                continue
            age = (current - updated).total_seconds()
            if not -30.0 <= age <= float(max_quote_age_seconds):
                continue

            outcomes = market.get("outcomes") or []
            if len(outcomes) != 2:
                continue
            home_outcome = next(
                (row for row in outcomes if isinstance(row, dict) and row.get("name") == home),
                None,
            )
            away_outcome = next(
                (row for row in outcomes if isinstance(row, dict) and row.get("name") == away),
                None,
            )
            if home_outcome is None or away_outcome is None:
                continue

            home_price = number(home_outcome.get("price"))
            away_price = number(away_outcome.get("price"))
            home_implied = implied(home_price)
            away_implied = implied(away_price)
            if home_implied is None or away_implied is None:
                continue
            total = home_implied + away_implied
            if total <= 0:
                continue

            basis = "provider_timestamp" if provider_updated is not None else "fresh_fetch_observed_at"
            timestamp_bases.add(basis)
            pairs.append(
                {
                    "book": book_name,
                    "updated": updated,
                    "home_price": home_price,
                    "away_price": away_price,
                    "home_probability": home_implied / total,
                }
            )

    if not pairs:
        return {**base, "home_team": home, "away_team": away}

    home_probability = mean(row["home_probability"] for row in pairs)
    home_quotes = [row for row in pairs if row["home_price"] is not None]
    away_quotes = [row for row in pairs if row["away_price"] is not None]
    best_home = max(home_quotes, key=lambda row: row["home_price"]) if home_quotes else None
    best_away = max(away_quotes, key=lambda row: row["away_price"]) if away_quotes else None
    latest = max(row["updated"] for row in pairs)
    books = sorted({row["book"] for row in pairs})

    return {
        **base,
        "status": "OK",
        "freshness_verified": True,
        "provider_timestamp_verified": "provider_timestamp" in timestamp_bases,
        "observed_at_verified": "fresh_fetch_observed_at" in timestamp_bases,
        "freshness_basis": sorted(timestamp_bases),
        "home_team": home,
        "away_team": away,
        "home_probability": home_probability,
        "away_probability": 1.0 - home_probability,
        "home_best_price": best_home["home_price"] if best_home else None,
        "home_best_book": best_home["book"] if best_home else None,
        "home_best_price_last_update": best_home["updated"].isoformat() if best_home else None,
        "away_best_price": best_away["away_price"] if best_away else None,
        "away_best_book": best_away["book"] if best_away else None,
        "away_best_price_last_update": best_away["updated"].isoformat() if best_away else None,
        "last_update": latest.isoformat(),
        "book_count": len(books),
        "books_used": books,
    }
