# PhilthySports runtime backend

Lean runtime for the Flutter client. It serves keyless schedules for NFL/NBA/MLB/NHL, an explicit four-sport market-baseline model registry, and fresh sportsbook odds/player props when a rotated server-side `ODDS_API_KEY` is configured.

Secrets must never be committed. Live sportsbook odds/props are disabled without a server-side credential. Execution is analytics/manual-review only.
