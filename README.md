# PhilthySports

PhilthySports combines a Flutter Android client with a deployed Python API for NFL, NBA, MLB, and NHL.

## Current runtime

- Homepage starts with **Search team, matchup, date, or sport**.
- NFL, NBA, MLB, and NHL each have a dedicated today's-games section.
- The deployed backend uses keyless schedule sources where available and an integrity-checked portable production-baseline bundle for all four sports.
- Each sport has a complete player-prop market catalog plus a quota-conscious default live subset. The contract remains visible before a sportsbook credential is activated, and callers can request a supported subset explicitly.
- Fresh sportsbook moneylines, spreads, totals, and player-prop prices require a newly issued server-side `ODDS_API_KEY` plus confirmed provider-side rotation. Exposed legacy keys are never reused.
- A trained sport model may replace the market baseline only after chronological walk-forward, separated calibration/holdout evaluation, provenance hashing, and promotion checks pass.
- Flutter retries transient gateway/rate-limit responses and temporary connection failures during backend validation before reverting a custom URL.\n- Provider credentials stay server-side. Never add them to Flutter, Android resources, assets, or GitHub.
- Execution remains analytics/manual-review only.

Backend: `https://philthysports-powerhouse-v8.onrender.com`

Current client version: **1.4.5+15**.
