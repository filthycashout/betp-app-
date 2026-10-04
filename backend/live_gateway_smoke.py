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

    parlay_board = backend._best_three_leg_parlays(today.isoformat())
    cards = parlay_board.get("cards") or []
    if parlay_board.get("parlays_per_sport") != 2:
        raise SystemExit("best3 contract did not return two parlays per sport")
    if parlay_board.get("legs_per_parlay") != 3:
        raise SystemExit("best3 contract did not return three-leg cards")
    if len(cards) != len(backend.SPORTS) * 2:
        raise SystemExit(f"best3 contract returned {len(cards)} cards instead of 8")

    for sport in backend.SPORTS:
        sport_cards = [card for card in cards if card.get("sport") == sport]
        if [card.get("rank") for card in sport_cards] != [1, 2]:
            raise SystemExit(f"{sport}: missing BEST 1/BEST 2 three-leg cards")
        for card in sport_cards:
            if not card.get("reasoning"):
                raise SystemExit(f"{sport}: best3 card has no overall reasoning")
            if card.get("status") == "OK":
                if len(card.get("legs") or []) != 3:
                    raise SystemExit(f"{sport}: OK best3 card did not contain three legs")
                if not all(leg.get("reason") for leg in card.get("legs") or []):
                    raise SystemExit(f"{sport}: best3 card has a leg without reasoning")

    print(json.dumps({"best_three_leg_parlays": parlay_board}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
