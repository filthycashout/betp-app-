from __future__ import annotations

import json

import app as backend
from keyless_sportsbook import draftkings_game_events, draftkings_prop_events


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
        events = draftkings_game_events(sport)
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
                f"{sport}: keyless DraftKings game-market canary returned no events"
            )
        if "h2h" not in sportsbook[sport]["market_keys"]:
            raise SystemExit(
                f"{sport}: keyless DraftKings board did not expose moneyline markets"
            )

    nfl_props = draftkings_prop_events(
        "NFL",
        backend.PROP_DEFAULT_LIVE_MARKETS["NFL"],
    )
    sportsbook["NFL"]["prop_events"] = len(nfl_props)
    sportsbook["NFL"]["prop_markets"] = sorted({
        market.get("key")
        for event in nfl_props
        for book in (event.get("bookmakers") or [])
        for market in (book.get("markets") or [])
        if market.get("key")
    })
    if not nfl_props:
        raise SystemExit(
            "NFL: keyless DraftKings player-prop canary returned no mapped events"
        )

    print(json.dumps({"keyless_sportsbook": sportsbook}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
