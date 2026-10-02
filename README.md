# PhilthySports

PhilthySports combines a Flutter Android client with a deployed Python API for NFL, NBA, MLB, and NHL.

## Current runtime

- Homepage starts with **Search team, matchup, date, or sport**.
- NFL, NBA, MLB, and NHL each have a dedicated today's-games section.
- The deployed backend uses keyless schedule sources where available and an integrity-checked portable production-baseline bundle for all four sports.
- Each sport has a player-prop market contract. The game screen shows supported prop markets even before a sportsbook credential is activated.
- Fresh sportsbook moneylines, spreads, totals, and player-prop prices require a newly issued server-side `ODDS_API_KEY`. Exposed legacy keys are never reused.
- A trained sport model may replace the market baseline only after chronological walk-forward, separated calibration/holdout evaluation, provenance hashing, and promotion checks pass.
- Provider credentials stay server-side. Never add them to Flutter, Android resources, assets, or GitHub.
- Execution remains analytics/manual-review only.

Backend: `https://philthysports-api-v9.onrender.com`

Current client version: **1.3.2+9**.
