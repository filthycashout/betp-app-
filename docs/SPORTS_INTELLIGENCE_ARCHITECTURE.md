# Sports Intelligence Architecture

## Purpose

Build a verified, five-sport intelligence pipeline for NFL, NBA, MLB, NHL, and UFC while preserving the repository's existing evidence, authorization, market-baseline, and model-promotion controls.

This is a target architecture mapped onto the current repository, not a claim that every proposed directory or capability already exists. Existing code remains the implementation source of truth until a reviewed migration replaces it.

## Architecture map

| Target area | Existing implementation / next home | Contract |
|---|---|---|
| `app/api/` | FastAPI routes in `backend/app.py`; progressively extract routers to `backend/api/` | Read-only endpoints, validated inputs, stable response schemas |
| `app/core/` | Shared config and model/runtime contracts in `backend/` | Explicit config, typed contracts, safe logging, fail-closed gates |
| `app/data/providers/` | Provider adapters in `backend/*` (including odds, ESPN/public context, and canary modules); extract to `backend/data/providers/` | Authorized sources only; provenance and quote timestamps retained |
| `app/data/validation.py` | Market validation and canonical admission under `backend/` and `backend/training/` | Reject malformed, stale, future-invalid, duplicate, or unprovenanced evidence |
| `app/data/caching.py` | Existing provider cache paths, where present; consolidate only after inventory | TTL by data type; no cache may make stale quotes look fresh |
| `app/sports/{nfl,nba,mlb,nhl,ufc}/` | Existing sport logic and `backend/sports/ufc/` starter contract | Sport-specific mapping over shared validated contracts |
| `app/models/` | `backend/model_runtime.py` and governed training/promotion paths | Market fallback until signed artifact passes strict promotion |
| `app/analytics/` | Existing market parsing, EV, calibration, and parlay logic in `backend/` | Correct odds math, evidence timestamps, explicit dependence status |
| `app/reporting/` | Chat picks briefing endpoint and export integrations | Every displayed claim traces to source evidence |
| `app/services/` | Existing training, evidence, and orchestration modules | Idempotent steps, bounded retries, explicit partial-failure state |
| `frontend/` | Existing frontend/mobile dashboard areas | Display source time, model state, and unavailable status |
| `tests/` | Existing backend tests; organize incrementally into unit/integration/fixtures | Deterministic fixtures, no dependence on live provider calls in unit tests |
| `scripts/` | Existing `.github/workflows/` and `backend/training/` commands | Scheduled jobs remain opt-in until deployment and evidence capture are verified |

Do not create a second API, duplicate model registry, or parallel odds cache just to match a folder diagram. Extract existing responsibilities incrementally, with compatibility tests before moving imports or routes.

## Sport coverage

- NFL, NBA, MLB, and NHL remain first-class existing sports.
- UFC is added as a fifth sport, initially as a validated event/market contract only.
- UFC must not be marked live-ready until a provider's MMA event coverage, market semantics, timestamp behavior, authorization, quota, and historical settlement data are verified.
- Missing UFC feeds return an explicit unavailable state. No event, price, prop, prediction, or parlay leg is fabricated to fill a board slot.

## Evidence and prediction flow

```text
authorized provider
  -> raw immutable response + provenance
  -> schema and timestamp validation
  -> canonical event / market mapping
  -> freshness and eligibility checks
  -> market baseline + candidate model
  -> calibrated EV / correlation analysis
  -> promotion and recommendation gates
  -> chat briefing / dashboard / exports
  -> settled result and evaluation
```

The following states are distinct: fetched, validated, canonical, training-eligible, candidate, promoted, and recommendation-eligible. A successful HTTP request or completed training command does not advance evidence through these states by itself.

## Required invariants

1. Use only authorized provider APIs and documented access methods.
2. Preserve provider, source event ID, bookmaker, line, price, quote timestamp, fetch timestamp, and normalization version.
3. Keep response-generation time separate from quote freshness.
4. Never silently substitute stale data for live data.
5. Keep unavailable sections and missing selections explicit.
6. Do not imply parlay-leg independence without a validated dependence model.
7. Keep automatic wagering disabled.
8. Model promotion requires the existing signed-artifact, provenance, leakage, chronological evaluation, calibration, and parity gates.
9. Production failures are diagnosed from actual logs and payloads; do not weaken guards to make checks green.

## Current verified blockers

The latest GitHub Actions run for PR #50 shows Secret Scan, Backend CI, and Unified Evidence CI passing, while the Floot Production Contract Guard fails. Its evidence report lists failed checks `game_detail`, `search_mlb`, `search_nba`, `search_nfl`, and `search_nhl`, each with zero returned games. Provider canary data in that report says The Odds API credential/catalog was authenticated and schema-valid, but the production probe still found no eligible games. This does not identify the root cause by itself; preserve the failure and inspect endpoint parameters, date windows, event filtering, and production logs before changing behavior.

The current runtime report also states market-baseline-only/manual-review mode and that trained models are blocked or missing. This architecture does not promote models or claim live picks as a side effect.

## Integration order

1. Resolve and verify production contract failures without relaxing checks.
2. Freeze common event, market, evidence, and section-status contracts.
3. Add the UFC contract and deterministic tests (this change).
4. Add a verified MMA provider adapter only after provider coverage/entitlement is confirmed.
5. Add UFC historical settlement and canonical training data; keep candidate-only until sample and evaluation gates pass.
6. Integrate five-sport analytics and reporting without changing the existing four-sport outputs.
7. Extract modules from `backend/app.py` behind compatibility tests.
8. Enable scheduled capture only after production endpoint, durable evidence storage, and freshness checks pass.
9. Connect ChatGPT through a deployed reachable API action/connector; a repository endpoint alone does not connect every chat.

## Acceptance tests

- Existing four-sport tests remain unchanged and pass.
- UFC event normalization rejects missing IDs, missing fighters, malformed start times, and non-future events when future-only mode is requested.
- UFC market normalization rejects invalid American prices, missing market identifiers, unknown selections, and missing quote timestamps.
- Every accepted UFC record retains provider identity, source event ID, observed timestamp, and canonical sport `UFC`.
- UFC capability status is `UNAVAILABLE` until an explicitly configured and verified adapter exists.
- A missing UFC feed cannot create a pick or parlay leg.
- The production contract guard remains failing until real production probes satisfy its current checks.
