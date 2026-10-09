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
