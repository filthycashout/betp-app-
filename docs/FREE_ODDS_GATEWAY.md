# PhilthySports FreeOddsGateway

The gateway is a read-only market-data path. It does not place wagers.

## Routing order

```text
Primary current game odds
  ESPN keyless scoreboard odds
        |
        v
Multi-book verification
  oddswrap
  DraftKings / FanDuel / BetMGM / Caesars / BetRivers / Bovada
        |
        v
Player props
  oddswrap
  DraftKings / FanDuel / BetRivers / Bovada where the upstream adapter exposes props
        |
        v
Free fallback
  PropLine (PROPLINE_API_KEY)
  odds-api.io (ODDS_API_IO_KEY; schema-guarded fallback)
        |
        v
Secondary market signal
  SX Bet public read API (no key required for REST reads)
        |
        v
Immutable PhilthySports snapshot
  canonical SHA-256 identity
  append-only persistence
  fetched_at < event_time required
        |
        v
Outcome validation
  NFL: ESPN
  NBA: ESPN/NBA path
  MLB: MLB StatsAPI
  NHL: NHL Web API
        |
        v
Training evidence export
  chronology-valid snapshot + settled official outcome
```

## Evidence contract

`backend/evidence/market_snapshot_store.py` rejects any snapshot whose fetch time is at or after the event start. Accepted snapshots are canonicalized, SHA-256 hashed, and inserted append-only into `philthy_market_snapshots` when Postgres is available. The runtime-file fallback is append-only JSONL.

The training exporter `backend/training/free_odds_evidence.py` only emits snapshots that independently pass `fetched_at_utc < event_time_utc` and have a completed outcome from the official/keyless outcome adapter.

## Provider boundaries

- ESPN is the primary keyless game-market source.
- oddswrap is the multi-book verification layer. It is pinned to a reviewed commit in `backend/requirements.txt` for reproducibility.
- PropLine is optional and only used when configured with `PROPLINE_API_KEY`.
- odds-api.io is optional and only used when configured with `ODDS_API_IO_KEY`; unknown response shapes fail closed.
- SX Bet is used as a secondary read-only market signal. It does not become a primary probability input and the gateway contains no wallet signing or order-placement code.
- Existing credentialed providers remain lower-priority fail-available fallbacks and cannot outrank the composite gateway event.

## Why this avoids the previous workflow failure

The earlier repair workflow embedded a long Python program inside a YAML shell heredoc and failed before validation because escaped newline text leaked into Python source. This integration keeps the transformation in a checked-in Python file (`scripts/apply_free_odds_gateway.py`) and the workflow invokes that file directly. Syntax validation runs before tests and before any commit is pushed.


## Hardening completion — 1.6.10

The gateway now normalizes the current odds-api.io v3 bookmaker-map schema for ML, spread, total, and Player Props markets; uses odds-api.io only after ESPN/oddswrap/PropLine coverage remains incomplete; and fails closed on same-team events whose start times differ by more than 30 minutes.

ESPN-primary events are stamped with their sport before immutable hashing. The resulting snapshot hash, gateway provenance, and SX Bet event-scoped secondary signal are propagated into `/v1/search` and the immutable prediction ledger. The prediction-ledger verifier requires a valid chronology-marked snapshot hash for new FreeOddsGateway rows.

SX Bet remains read-only secondary evidence. The gateway matches SX markets to a specific event by teams and start time and never enables order placement.

The old self-mutating GitHub Action has been converted to validation-only. `scripts/apply_free_odds_gateway.py` now refuses to overwrite an already hardened 1.6.10 integration.


## Final evidence hardening — 1.6.11

Game fallback is now market-coverage-aware rather than merely event-aware: missing h2h, spread, or total verification can be filled by later providers, including within an already-present sportsbook. Player-prop fallbacks merge missing requested markets across oddswrap, PropLine, and odds-api.io instead of stopping at the first partial provider.

FreeOddsGateway snapshots report whether their backing storage is durable. A local runtime JSONL write is explicitly marked `RECORDED_NON_DURABLE`; strict prediction-ledger and canonical-training evidence require a durable, chronology-valid SHA-256 snapshot for FreeOddsGateway rows.

Canonical training rows now retain the gateway market source and snapshot provenance. The active production/evidence workflows no longer hard-code a retired Render host; repository variables select the active HTTPS backend and fail closed when no current backend has been configured. Model and Android signing fallbacks likewise no longer silently target a retired host.


## Latency hardening — 1.6.12

The FreeOddsGateway now caches short-lived read-only provider results, fetches oddswrap moneyline/spread/total families concurrently, runs SX Bet secondary evidence in parallel with primary multi-book verification, and limits SX read timeouts. Player-prop discovery is built once per sport/requested-market set, with sportsbook discovery and category fetches parallelized and the resulting league catalog reused while scanning scheduled games.

These controls preserve fail-closed semantics: timeout/fetch failures reduce verified coverage rather than inventing a line. They specifically remove the repeated provider fan-out that caused Best 12, Best 3, and 7/10/14-leg board routes to exceed the portable API contract timeout.
