---
name: odds-api-research
description: Retrieve or design governed sports-odds workflows with odds-api/odds-api and PhilthySports. Use for bookmaker comparisons, market schemas, fair/no-vig prices, line movement, results, arbitrage research, positive-EV research, streaming, freshness checks and live-provider provenance.
---

# Odds API Research

PhilthySports uses two separate layers:

- `odds-api-docs`: GitMCP documentation/context for `odds-api/odds-api`.
- Native `@odds-api/mcp`: optional live odds-api.net tool server when explicitly configured.
- PhilthySports production MCP: governed application-facing access through `https://philthysports-mcp-v1.onrender.com/mcp`.

## Pinned upstream

- Repository: `odds-api/odds-api`
- Branch: `main`
- Verified current commit: `1b8d4bdddf01c610eb725dc610f12ab53a20dba8`
- PhilthySports lock: `integrations/upstreams.lock.json`

## Credential isolation

Do not confuse different odds providers.

- PhilthySports/The Odds API credential: `THE_ODDS_API_KEY`.
- odds-api.net credential at the PhilthySports/config boundary: `ODDS_API_NET_KEY`.
- The native `@odds-api/mcp` child process expects `ODDS_API_KEY`; map `ODDS_API_NET_KEY` to that child-process variable only in its launch config.

Never reuse, alias or copy a credential between providers. Keep every key server-side and out of APKs, screenshots, logs and committed files.

## Production surfaces

- `philthy_provider_status`: provider/routing availability without secret values.
- `philthy_search`: governed live game/market research where the backend has valid evidence.
- `philthy_best12` / `philthy_best3`: analysis outputs only; they never execute a wager.
- `philthy_evidence`: provenance/freshness evidence used by the backend.

## Workflow

1. Use `odds-api-docs` to confirm current parameters, market names, schemas, pagination, streaming behavior and SDK/MCP examples.
2. For current prices, use only an authenticated live provider path. Documentation examples and mock responses are not live sportsbook evidence.
3. Record `source`, `retrieved_at`, provider timestamp, event ID, bookmaker, market, selection, price and line/handicap for every observation.
4. Enforce quote freshness. Stale, suspended, missing or unmatched markets fail closed rather than being imputed or fabricated.
5. When comparing prices, distinguish raw bookmaker odds from fair/no-vig estimates. Missing fair prices remain missing.
6. For line movement, compare chronological snapshots of the same event/market/selection/line; do not mix unmatched handicaps or totals.
7. Settlement/results belong in post-event evidence only and must never leak into pregame features.
8. Mock mode is permitted only for development/smoke tests and must be explicitly labeled `mock`; it never satisfies production evidence requirements.
9. Arbitrage/positive-EV calculations are research outputs subject to latency, limits, market suspension, voids and execution risk. Do not claim guaranteed profit.
10. No MCP tool may place a wager, deposit funds or operate a sportsbook account.

## Output contract

Return the queried event/market, provider identity, retrieval/provider timestamps, freshness decision, bookmakers compared, normalization/no-vig assumptions, derived calculations, missing/suspended/stale data and whether mock/test data was used.
