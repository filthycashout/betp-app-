# Floot Cutover Status — 2026-10-07

Source branch: `floot-production-cutover-20261007`
Base commit: `c951145efec43c031565549620eeaf6fffed61c0`
Floot project: `2349a7ae-bd42-45fb-8412-feda5700b916`
Production hostname: `https://philthyparleys.floot.app`
Floot API namespace: `https://philthyparleys.floot.app/_api`
Render rollback: `https://philthysports-api-v9.onrender.com`

## Verified on Floot

- Managed Postgres is provisioned and durable.
- `ODDS_API_KEY` and `SPORTRADAR_API_KEY` are connected as server-side secrets.
- Production `/_api/health`, `/_api/v1/system/status`, and `/_api/v1/providers/canary` returned HTTP 200 before the latest unpublished compatibility edits.
- Live The Odds API credential authenticated and schema validation passed.
- Immutable NFL and NBA pregame snapshots were persisted in Postgres.
- Snapshot rows carry SHA-256 checksums; the migration added deterministic signal identifiers derived from those checksums.
- NFL/NBA market-baseline probabilities are de-vigged from live sportsbook evidence. No trained-model promotion is claimed.
- Model gates remain fail-closed and market-baseline fallback remains explicit.

## GitHub cutover changes

- Flutter backend default is staged to Floot on this branch.
- A one-time migration moves the prior default Render URL to Floot, while a deliberate manual save of the Render URL remains a valid rollback.
- Flutter API requests rewrite Floot calls through `/_api`.
- Dynamic game/evidence routes are translated to fixed Floot query endpoints because Floot endpoints do not support dynamic route parameters.
- Mobile WebView networking allows only approved read-only Floot routes; signing/admin routes remain blocked.
- `ci/floot_cutover_smoke.py` and `.github/workflows/floot-cutover-guard.yml` require the complete mobile/dashboard production contract before promotion.

## Current blocker

The Floot workspace reached its daily build-action limit after the initial production publish and subsequent development changes. The latest compatibility/search/evidence changes therefore exist in the Floot development project but could not be republished during this run. The cutover guard is intentionally expected to fail until the remaining production contracts are implemented and republished.

Required contracts before promotion include:

- legacy-compatible health identity (`status=ok`, `service=philthysports-runtime`)
- NFL and NBA search feeds on production
- model status and registry
- prop capabilities
- provider inventory
- evidence signal listing and verification
- fixed game detail/props/best9 endpoints
- best-12 picks
- best-3 cards
- 7/10/14-leg multisport endpoints

The branch must not be merged merely because `/health` is green. The Floot Cutover Guard must pass first. Android signing/emulator/physical-device acceptance and trained-model promotion remain separate gates.
