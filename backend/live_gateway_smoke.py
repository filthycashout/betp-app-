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


if __name__ == "__main__":
    main()
