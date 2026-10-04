"""Validation of event-level prop prices. No provider bodies or secrets are logged."""
from datetime import datetime, timezone
from math import isfinite
from statistics import mean

MAX_QUOTE_AGE_SECONDS = 300


def utc_time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


def number(value):
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (TypeError, ValueError):
        return None


def implied(value):
    price = number(value)
    if price is None or abs(price) < 100:
        return None
    return -price / (100 - price) if price < 0 else 100 / (100 + price)


def parse_props(raw, sport, markets, now=None):
    now = now or datetime.now(timezone.utc)
    start = utc_time(raw.get("commence_time"))
    if start is None or start <= now:
        return {
            "props": [],
            "status": "NO_VERIFIED_PREGAME_EVENT",
            "message": "A verified future start time is required for pregame prop recommendations.",
        }

    groups = {}
    skipped = 0
    for book in raw.get("bookmakers") or []:
        book_name = book.get("key") or book.get("title") or "unknown"
        for market in book.get("markets") or []:
            key = market.get("key")
            if key not in markets:
                continue
            provider_updated = utc_time(
                market.get("last_update") or book.get("last_update")
            )
            observed = utc_time(
                market.get("observed_at") or book.get("observed_at")
            )
            updated = provider_updated or observed
            if (
                updated is None
                or not -30
                <= (now - updated).total_seconds()
                <= MAX_QUOTE_AGE_SECONDS
            ):
                skipped += 1
                continue
            timestamp_basis = (
                "provider_timestamp"
                if provider_updated is not None
                else "fresh_fetch_observed_at"
            )

            local = {}
            for outcome in market.get("outcomes") or []:
                price = number(outcome.get("price"))
                probability = implied(price)
                player = str(
                    outcome.get("description") or outcome.get("name") or ""
                ).strip()
                side = str(outcome.get("name") or "").strip()
                line = number(outcome.get("point"))
                if probability is None or price is None or not player or not side:
                    continue
                if outcome.get("point") is not None and line is None:
                    continue
                if side.lower() in {"over", "under"} and line is None:
                    continue
                local.setdefault((key, player, line), {})[side.lower()] = {
                    "probability": probability,
                    "price": price,
                }

            for identity, sides in local.items():
                entry = groups.setdefault(
                    identity,
                    {
                        "pairs": [],
                        "quotes": {},
                        "prices": {},
                        "books": set(),
                        "updates": [],
                        "timestamp_bases": set(),
                    },
                )
                entry["books"].add(book_name)
                entry["updates"].append(updated)
                entry["timestamp_bases"].add(timestamp_basis)
                for side, quote in sides.items():
                    entry["quotes"].setdefault(side, []).append(
                        quote["probability"]
                    )
                    entry["prices"].setdefault(side, []).append(
                        {
                            "book": book_name,
                            "price": quote["price"],
                            "last_update": updated.isoformat(),
                        }
                    )
                for first, second in (("over", "under"), ("yes", "no")):
                    if first in sides and second in sides:
                        first_probability = sides[first]["probability"]
                        second_probability = sides[second]["probability"]
                        total = first_probability + second_probability
                        entry["pairs"].append(
                            {
                                "first": first,
                                "second": second,
                                "first_probability": first_probability / total,
                                "book": book_name,
                                "first_price": sides[first]["price"],
                                "second_price": sides[second]["price"],
                                "last_update": updated.isoformat(),
                            }
                        )
                        break

    props = []
    for (market, player, line), entry in groups.items():
        base = {
            "sport": sport,
            "market": market,
            "player": player,
            "line": line,
            "book_count": len(entry["books"]),
            "contributing_books": sorted(entry["books"]),
            "last_update": min(entry["updates"]).isoformat(),
            "freshness_basis": sorted(entry["timestamp_bases"]),
            "provider_timestamp_verified": "provider_timestamp" in entry["timestamp_bases"],
            "observed_at_verified": "fresh_fetch_observed_at" in entry["timestamp_bases"],
            "model_state": "MARKET_ONLY_UNTIL_VALIDATED_PROP_MODEL",
        }
        pairs = entry["pairs"]
        if pairs:
            first = pairs[0]["first"]
            second = pairs[0]["second"]
            matching = [
                pair
                for pair in pairs
                if pair["first"] == first and pair["second"] == second
            ]
            p = mean(pair["first_probability"] for pair in matching)
            side, probability = (
                (first.upper(), p)
                if p >= 0.5
                else (second.upper(), 1 - p)
            )
            side_prices = entry["prices"].get(side.lower()) or []
            best = max(side_prices, key=lambda quote: quote["price"]) if side_prices else None
            props.append(
                {
                    **base,
                    "outcome": side,
                    "recommended_side": side,
                    "market_probability": probability,
                    "probability_method": "same_book_two_sided_devig",
                    "paired_book_count": len(matching),
                    "best_available_price": best["price"] if best else None,
                    "best_available_book": best["book"] if best else None,
                    "best_price_last_update": best["last_update"] if best else None,
                    "reason": (
                        f"Market lean {side} at {probability:.1%}, using "
                        "complementary prices from the same bookmaker and line. "
                        "The listed best price is a fresh contributing quote; "
                        "the probability is de-vigged consensus, not a trained prop forecast."
                    ),
                }
            )
        else:
            for side, probabilities in entry["quotes"].items():
                side_prices = entry["prices"].get(side) or []
                best = max(side_prices, key=lambda quote: quote["price"]) if side_prices else None
                props.append(
                    {
                        **base,
                        "outcome": side.upper(),
                        "recommended_side": None,
                        "market_probability": mean(probabilities),
                        "probability_method": "raw_implied_not_devigged",
                        "best_available_price": best["price"] if best else None,
                        "best_available_book": best["book"] if best else None,
                        "best_price_last_update": best["last_update"] if best else None,
                        "reason": (
                            "Price available; no same-book complementary outcome "
                            "supports a de-vigged recommendation."
                        ),
                    }
                )

    props.sort(key=lambda x: x["market_probability"], reverse=True)
    return {
        "props": props,
        "status": "OK" if props else "NO_FRESH_MARKETS",
        "rejected_stale_or_undated_markets": skipped,
        "quote_max_age_seconds": MAX_QUOTE_AGE_SECONDS,
        "fetched_at": now.isoformat(),
        "message": (
            "Fresh provider prices validated."
            if props
            else "No current, timestamped player-prop prices were returned for the selected event and markets."
        ),
    }

def parse_game_market(event, now=None):
    """Use paired book prices at an actual offered line, never an average line."""
    now = now or datetime.now(timezone.utc)
    out = dict.fromkeys([
        'home_probability', 'away_probability', 'moneyline_pick',
        'moneyline_pick_probability', 'moneyline_best_price',
        'moneyline_best_book', 'moneyline_last_update',
        'home_spread', 'away_spread', 'spread_home_probability',
        'spread_away_probability', 'spread_pick', 'spread_pick_probability',
        'spread_best_price', 'spread_best_book', 'spread_last_update',
        'total', 'over_probability', 'under_probability', 'total_pick',
        'total_pick_probability', 'total_best_price', 'total_best_book',
        'total_last_update', 'last_update',
    ])
    out.update(
        books_used=[],
        freshness_verified=False,
        provider_timestamp_verified=False,
        observed_at_verified=False,
        freshness_basis=[],
    )
    if not event:
        return out
    start = utc_time(event.get('commence_time'))
    if not start or start <= now:
        return out

    home, away = event.get('home_team'), event.get('away_team')
    money = []
    spreads = {}
    totals = {}
    books = set()
    fresh_updates = []

    for book in event.get('bookmakers') or []:
        book_name = book.get('key') or book.get('title') or 'unknown'
        for market in book.get('markets') or []:
            provider_updated = utc_time(
                market.get('last_update') or book.get('last_update')
            )
            observed = utc_time(
                market.get('observed_at') or book.get('observed_at')
            )
            updated = provider_updated or observed
            fresh = (
                updated is not None
                and -30 <= (now - updated).total_seconds() <= MAX_QUOTE_AGE_SECONDS
            )
            if fresh:
                fresh_updates.append(updated)
            if fresh and provider_updated is not None:
                out['provider_timestamp_verified'] = True
                if 'provider_timestamp' not in out['freshness_basis']:
                    out['freshness_basis'].append('provider_timestamp')
            elif fresh and observed is not None:
                out['observed_at_verified'] = True
                if 'fresh_fetch_observed_at' not in out['freshness_basis']:
                    out['freshness_basis'].append('fresh_fetch_observed_at')

            outcomes = market.get('outcomes') or []
            key = market.get('key')
            names = (home, away) if key in {'h2h', 'spreads'} else ('Over', 'Under')
            a = next((o for o in outcomes if o.get('name') == names[0]), None)
            b = next((o for o in outcomes if o.get('name') == names[1]), None)
            if not a or not b:
                continue

            a_price = number(a.get('price'))
            b_price = number(b.get('price'))
            pa, pb = implied(a_price), implied(b_price)
            probability = (
                pa / (pa + pb)
                if fresh and pa is not None and pb is not None
                else None
            )

            if key == 'h2h':
                if len(outcomes) == 2 and probability is not None:
                    money.append({
                        'probability': probability,
                        'home_price': a_price,
                        'away_price': b_price,
                        'book': book_name,
                        'updated': updated,
                    })
                    books.add(book_name)
                continue

            if key not in {'spreads', 'totals'}:
                continue
            point, other = number(a.get('point')), number(b.get('point'))
            if point is None or other is None:
                continue
            if (
                (key == 'spreads' and abs(point + other) > 1e-8)
                or (key == 'totals' and point != other)
            ):
                continue

            group = (spreads if key == 'spreads' else totals).setdefault(
                point,
                {'quotes': 0, 'probs': [], 'pairs': []},
            )
            group['quotes'] += 1
            if probability is not None:
                group['probs'].append(probability)
                group['pairs'].append({
                    'probability': probability,
                    'first_price': a_price,
                    'second_price': b_price,
                    'book': book_name,
                    'updated': updated,
                })
                books.add(book_name)

    if money:
        hp = mean(row['probability'] for row in money)
        home_pick = hp >= 0.5
        side_quotes = [
            {
                'price': row['home_price'] if home_pick else row['away_price'],
                'book': row['book'],
                'updated': row['updated'],
            }
            for row in money
            if (row['home_price'] if home_pick else row['away_price']) is not None
        ]
        best = max(side_quotes, key=lambda row: row['price']) if side_quotes else None
        out.update(
            home_probability=hp,
            away_probability=1 - hp,
            moneyline_pick=home if home_pick else away,
            moneyline_pick_probability=max(hp, 1 - hp),
            moneyline_best_price=best['price'] if best else None,
            moneyline_best_book=best['book'] if best else None,
            moneyline_last_update=(
                max(row['updated'] for row in money if row['updated']).isoformat()
                if any(row['updated'] for row in money)
                else None
            ),
        )

    for groups, prefix in ((spreads, 'spread'), (totals, 'total')):
        if not groups:
            continue
        # Prefer lines supported by verified two-sided prices, then book coverage.
        point, group = max(
            groups.items(),
            key=lambda x: (len(x[1]['probs']), x[1]['quotes'], -abs(x[0])),
        )
        if prefix == 'spread':
            out.update(home_spread=point, away_spread=-point)
        else:
            out['total'] = point
        if not group['probs']:
            continue

        p = mean(group['probs'])
        out['freshness_verified'] = True
        first_pick = p >= 0.5
        side_quotes = [
            {
                'price': row['first_price'] if first_pick else row['second_price'],
                'book': row['book'],
                'updated': row['updated'],
            }
            for row in group['pairs']
            if (row['first_price'] if first_pick else row['second_price']) is not None
        ]
        best = max(side_quotes, key=lambda row: row['price']) if side_quotes else None
        last_update = (
            max(row['updated'] for row in group['pairs'] if row['updated']).isoformat()
            if any(row['updated'] for row in group['pairs'])
            else None
        )

        if prefix == 'spread':
            out.update(
                spread_home_probability=p,
                spread_away_probability=1 - p,
                spread_pick=home if first_pick else away,
                spread_pick_probability=max(p, 1 - p),
                spread_best_price=best['price'] if best else None,
                spread_best_book=best['book'] if best else None,
                spread_last_update=last_update,
            )
        else:
            out.update(
                over_probability=p,
                under_probability=1 - p,
                total_pick='OVER' if first_pick else 'UNDER',
                total_pick_probability=max(p, 1 - p),
                total_best_price=best['price'] if best else None,
                total_best_book=best['book'] if best else None,
                total_last_update=last_update,
            )

    out['freshness_verified'] = out['freshness_verified'] or bool(money)
    out['books_used'] = sorted(books)
    out['last_update'] = (
        max(fresh_updates).isoformat() if fresh_updates else None
    )
    return out
