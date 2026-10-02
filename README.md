# PhilthySports

Flutter Android client plus deployable Python runtime backend for NFL, NBA, MLB, and NHL.

## Runtime behavior

- Homepage starts with **Search team, matchup, date, or sport**.
- Separate NFL, NBA, MLB, and NHL sections show today's schedule.
- Every sport has a player-prop contract. Live sportsbook prices require a rotated server-side `ODDS_API_KEY`.
- The backend exposes a portable `MARKET_BASELINE_ACTIVE` model for all four sports. It is not mislabeled as trained weights.
- Chronologically promoted calibrated models may override the market baseline only after the model-governance gates pass.
- Provider credentials stay server-side. Never add them to Flutter, Android resources, assets, or GitHub.
- Execution remains analytics/manual-review only.

Current client version: **1.3.0+7**.
