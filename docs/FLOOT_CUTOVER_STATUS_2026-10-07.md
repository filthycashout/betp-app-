# Floot Cutover Status — 2026-10-07

Source branch: `floot-production-cutover-20261007`
Base commit: `c951145efec43c031565549620eeaf6fffed61c0`
Floot project: `2349a7ae-bd42-45fb-8412-feda5700b916`
Production hostname: `https://philthyparleys.floot.app`
Floot API namespace: `https://philthyparleys.floot.app/_api`
Legacy Render backend: **RETIRED — not a production or rollback target**

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

- Flutter backend default is Floot.
- Saved legacy Render backend values are treated as obsolete and migrate to the current Floot default; the Android network bridge no longer permits the retired Render host.
- Flutter API requests rewrite Floot calls through `/_api`.
- Dynamic game/evidence routes are translated to fixed Floot query endpoints because Floot endpoints do not support dynamic route parameters.
- Mobile WebView networking allows only approved read-only Floot routes; signing/admin routes remain blocked.
- `ci/floot_cutover_smoke.py` and `.github/workflows/floot-cutover-guard.yml` require the complete mobile/dashboard production contract before promotion.
- GitHub evidence capture, provider proof, production guard, and durable-storage verification target Floot rather than the retired Render backend.

## Current blocker

The latest compatibility/search/evidence changes exist in the Floot development project but have not yet been promoted to the published production deployment. The production guard therefore remains intentionally fail-closed while published Floot is missing required compatibility routes. This document does not treat a stale production deployment as equivalent to the tested development project.

Required production contracts include:

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

The production deployment must not be promoted merely because `/health` is green. The Floot Cutover Guard must pass first. Android signing/emulator/physical-device acceptance, fresh evidence capture, live-provider proof, and trained-model promotion remain separate gates.
