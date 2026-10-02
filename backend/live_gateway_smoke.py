from __future__ import annotations

import json

import app as backend
from keyless_sportsbook import keyless_game_events, keyless_prop_events


def main() -> None:
    checks = {}
    today = backend._pacific_today()

    for sport in backend.SPORTS:
        payload = backend._keyless_live_scoreboard(sport, today)
        if payload.get("credential_required") is not False:
            raise SystemExit(f"{sport}: keyless gateway unexpectedly requires credentials")
        games = payload.get("games")
        if not isinstance(games, list):
            raise SystemExit(f"{sport}: gateway did not return a games list")
        checks[sport] = {
            "provider": payload.get("provider"),
            "date": payload.get("date"),
            "games": len(games),
            "credential_required": payload.get("credential_required"),
        }

    print(json.dumps(checks, indent=2, sort_keys=True))

    sportsbook = {}
    for sport in backend.SPORTS:
        events = keyless_game_events(sport)
        market_keys = sorted({
            market.get("key")
            for event in events
            for book in (event.get("bookmakers") or [])
            for market in (book.get("markets") or [])
            if market.get("key")
        })
        sportsbook[sport] = {
            "events": len(events),
            "market_keys": market_keys,
        }

    for sport in ("NFL", "NHL"):
        if sportsbook[sport]["events"] <= 0:
            raise SystemExit(
                f"{sport}: keyless sportsbook game-market canary returned no events"
            )
        if "h2h" not in sportsbook[sport]["market_keys"]:
            raise SystemExit(
                f"{sport}: keyless sportsbook board did not expose moneyline markets"
            )

    for sport in backend.SPORTS:
        prop_events = keyless_prop_events(
            sport,
            backend.PROP_DEFAULT_LIVE_MARKETS[sport],
        )
        sportsbook[sport]["prop_events"] = len(prop_events)
        sportsbook[sport]["prop_markets"] = sorted({
            market.get("key")
            for event in prop_events
            for book in (event.get("bookmakers") or [])
            for market in (book.get("markets") or [])
            if market.get("key")
        })

    for sport in ("NFL", "NHL"):
        if sportsbook[sport]["prop_events"] <= 0:
            raise SystemExit(
                f"{sport}: keyless sportsbook player-prop canary returned no mapped events"
            )

    print(json.dumps({"keyless_sportsbook": sportsbook}, indent=2, sort_keys=True))

    available_candidates, _ = backend._multisport_candidates(
        backend._pacific_today(),
        target_count=56,
        horizon_days=4,
    )
    available_candidate_sports = {
        str(row.get("sport") or "")
        for row in available_candidates
        if row.get("sport")
    }

    parlay_canary = {}
    for legs in (7, 10, 14):
        card = backend._build_multisport_parlay(
            legs,
            backend._pacific_today().isoformat(),
        )
        parlay_canary[str(legs)] = {
            "status": card.get("status"),
            "actual_legs": card.get("actual_legs"),
            "player_prop_legs": card.get("player_prop_legs"),
            "sports_included": card.get("sports_included"),
            "dependency_method": card.get("dependency_method"),
        }
        if card.get("actual_legs") != legs:
            raise SystemExit(
                f"{legs}-leg live parlay canary returned {card.get('actual_legs')} legs"
            )
        if card.get("multisport") is not True:
            raise SystemExit(f"{legs}-leg live parlay canary is not multisport")
        if set(card.get("sports_included") or []) != available_candidate_sports:
            raise SystemExit(
                f"{legs}-leg live parlay did not cover every eligible candidate sport: "
                f"card={card.get('sports_included')} "
                f"eligible={sorted(available_candidate_sports)}"
            )
        if int(card.get("player_prop_legs") or 0) <= 0:
            raise SystemExit(
                f"{legs}-leg live parlay canary did not include a player prop"
            )
        if not card.get("reasoning"):
            raise SystemExit(f"{legs}-leg live parlay has no overall reasoning")
        if not all(leg.get("reason") for leg in card.get("legs") or []):
            raise SystemExit(f"{legs}-leg live parlay has a leg without reasoning")

    print(json.dumps({"live_parlays": parlay_canary}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
