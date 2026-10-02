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
        return {"props": [], "status": "NO_VERIFIED_PREGAME_EVENT", "message": "A verified future start time is required for pregame prop recommendations."}
    groups = {}
    skipped = 0
    for book in raw.get("bookmakers") or []:
        for market in book.get("markets") or []:
            key = market.get("key")
            if key not in markets:
                continue
            updated = utc_time(market.get("last_update") or book.get("last_update"))
            if updated is None or not -30 <= (now - updated).total_seconds() <= MAX_QUOTE_AGE_SECONDS:
                skipped += 1
                continue
            local = {}
            for outcome in market.get("outcomes") or []:
                probability = implied(outcome.get("price"))
                player = str(outcome.get("description") or outcome.get("name") or "").strip()
                side = str(outcome.get("name") or "").strip()
                line = number(outcome.get("point"))
                if probability is None or not player or not side:
                    continue
                if outcome.get("point") is not None and line is None:
                    continue
                if side.lower() in {"over", "under"} and line is None:
                    continue
                local.setdefault((key, player, line), {})[side.lower()] = probability
            for identity, sides in local.items():
                entry = groups.setdefault(identity, {"pairs": [], "quotes": {}, "books": set(), "updates": []})
                entry["books"].add(book.get("key") or book.get("title") or "unknown")
                entry["updates"].append(updated)
                for side, probability in sides.items():
                    entry["quotes"].setdefault(side, []).append(probability)
                for first, second in (("over", "under"), ("yes", "no")):
                    if first in sides and second in sides:
                        total = sides[first] + sides[second]
                        entry["pairs"].append((first, second, sides[first] / total))
                        break
    props = []
    for (market, player, line), entry in groups.items():
        base = {"sport": sport, "market": market, "player": player, "line": line,
                "book_count": len(entry["books"]), "last_update": min(entry["updates"]).isoformat(),
                "model_state": "MARKET_ONLY_UNTIL_VALIDATED_PROP_MODEL"}
        pairs = entry["pairs"]
        if pairs:
            first, second = pairs[0][:2]
            p = mean(x[2] for x in pairs if x[:2] == (first, second))
            side, probability = (first.upper(), p) if p >= .5 else (second.upper(), 1 - p)
            props.append({**base, "outcome": side, "recommended_side": side,
                          "market_probability": probability, "probability_method": "same_book_two_sided_devig",
                          "paired_book_count": len(pairs),
                          "reason": f"Market lean {side} at {probability:.1%}, using complementary prices from the same bookmaker and line. This is market consensus, not a trained prop forecast."})
        else:
            for side, probabilities in entry["quotes"].items():
                props.append({**base, "outcome": side.upper(), "recommended_side": None,
                              "market_probability": mean(probabilities), "probability_method": "raw_implied_not_devigged",
                              "reason": "Price available; no same-book complementary outcome supports a de-vigged recommendation."})
    props.sort(key=lambda x: x["market_probability"], reverse=True)
    return {"props": props, "status": "OK" if props else "NO_FRESH_MARKETS",
            "rejected_stale_or_undated_markets": skipped, "quote_max_age_seconds": MAX_QUOTE_AGE_SECONDS,
            "fetched_at": now.isoformat(),
            "message": "Fresh provider prices validated." if props else "No current, timestamped player-prop prices were returned for the selected event and markets."}


def parse_game_market(event, now=None):
    """Use paired book prices at an actual offered line, never an average line."""
    now = now or datetime.now(timezone.utc)
    out = dict.fromkeys(['home_probability','away_probability','home_spread','away_spread',
                         'spread_home_probability','spread_away_probability','spread_pick',
                         'spread_pick_probability','total','over_probability','under_probability',
                         'total_pick','total_pick_probability'])
    out.update(books_used=[], freshness_verified=False)
    if not event:
        return out
    start=utc_time(event.get('commence_time'))
    if not start or start <= now:
        return out
    home,away=event.get('home_team'),event.get('away_team')
    money=[];spreads={};totals={};books=set()
    for book in event.get('bookmakers') or []:
        for market in book.get('markets') or []:
            updated=utc_time(market.get('last_update') or book.get('last_update'))
            fresh=updated is not None and -30 <= (now-updated).total_seconds() <= MAX_QUOTE_AGE_SECONDS
            outcomes=market.get('outcomes') or []
            key=market.get('key')
            names=(home,away) if key in {'h2h','spreads'} else ('Over','Under')
            a=next((o for o in outcomes if o.get('name')==names[0]),None)
            b=next((o for o in outcomes if o.get('name')==names[1]),None)
            if not a or not b: continue
            pa,pb=implied(a.get('price')),implied(b.get('price'))
            probability=pa/(pa+pb) if fresh and pa is not None and pb is not None else None
            if key=='h2h':
                if len(outcomes)==2 and probability is not None:
                    money.append(probability);books.add(book.get('key') or 'unknown')
                continue
            if key not in {'spreads','totals'}:continue
            point,other=number(a.get('point')),number(b.get('point'))
            if point is None or other is None:continue
            if (key=='spreads' and abs(point+other)>1e-8) or (key=='totals' and point!=other):continue
            group=(spreads if key=='spreads' else totals).setdefault(point,{'quotes':0,'probs':[]})
            group['quotes']+=1
            if probability is not None:group['probs'].append(probability)
            books.add(book.get('key') or 'unknown')
    if money:
        out['home_probability']=mean(money);out['away_probability']=1-out['home_probability']
    for groups,prefix in ((spreads,'spread'),(totals,'total')):
        if not groups:continue
        # Prefer lines supported by verified two-sided prices, then book coverage.
        point,group=max(groups.items(),key=lambda x:(len(x[1]['probs']),x[1]['quotes'],-abs(x[0])))
        if prefix=='spread':out.update(home_spread=point,away_spread=-point)
        else:out['total']=point
        if not group['probs']:continue
        p=mean(group['probs']);out['freshness_verified']=True
        if prefix=='spread':
            out.update(spread_home_probability=p,spread_away_probability=1-p,
                       spread_pick=home if p>=.5 else away,spread_pick_probability=max(p,1-p))
        else:
            out.update(over_probability=p,under_probability=1-p,total_pick='OVER' if p>=.5 else 'UNDER',total_pick_probability=max(p,1-p))
    out['freshness_verified']=out['freshness_verified'] or bool(money)
    out['books_used']=sorted(books)
    return out
