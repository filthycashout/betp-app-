from __future__ import annotations

import json

import app as backend


def main() -> None:
    # Use the next known NFL Sunday from the release date. This intentionally
    # exercises live keyless schedule/odds/recent-form providers without secrets.
    payload = backend._search(
        sport="NFL",
        date="2026-10-04",
        include_props=False,
    )
    games = payload.get("games") or []
    if not games:
        raise SystemExit("live smoke: NFL schedule returned no games for 2026-10-04")

    generated = [
        game for game in games
        if bool((game.get("predictions") or {}).get("generated"))
    ]
    summary = [
        {
            "matchup": game.get("matchup"),
            "pick": game.get("pick"),
            "source": game.get("probability_source"),
            "generated": bool((game.get("predictions") or {}).get("generated")),
            "score": game.get("projected_score"),
        }
        for game in games
    ]
    print(json.dumps(summary, indent=2, sort_keys=True))

    if not generated:
        raise SystemExit(
            "live smoke: schedule loaded but no matchup generated a prediction"
        )

    fallback_generated = [
        game for game in generated
        if str(game.get("probability_source") or "").startswith("keyless_")
    ]
    market_generated = [
        game for game in generated
        if game.get("probability_source")
        in {"fresh_de_vigged_consensus_moneyline", "signed_promoted_trained_model"}
    ]
    print(
        json.dumps(
            {
                "games": len(games),
                "generated": len(generated),
                "keyless_fallback_generated": len(fallback_generated),
                "market_or_promoted_generated": len(market_generated),
            },
            indent=2,
            sort_keys=True,
        )
    )

    # Regression for the physical-device screenshot: today's NHL cards must no
    # longer all collapse to ML/projected-score unavailable.
    nhl = backend._search(
        sport="NHL",
        date=backend._pacific_today().isoformat(),
        include_props=False,
    )
    nhl_games = nhl.get("games") or []
    nhl_generated = [
        game
        for game in nhl_games
        if bool((game.get("predictions") or {}).get("generated"))
    ]
    print(
        json.dumps(
            {
                "nhl_today_games": len(nhl_games),
                "nhl_generated": len(nhl_generated),
                "nhl_sources": sorted({
                    str(game.get("probability_source") or "")
                    for game in nhl_generated
                }),
            },
            indent=2,
            sort_keys=True,
        )
    )
    if nhl_games and not nhl_generated:
        raise SystemExit(
            "live smoke: today's NHL board loaded but every matchup remained unavailable"
        )


if __name__ == "__main__":
    main()
