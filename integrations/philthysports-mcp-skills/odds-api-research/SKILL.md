---
name: odds-api-research
description: Retrieve or design workflows for sports betting odds, bookmaker comparisons, market schemas, fair prices, line movement, results, arbitrage research, positive-EV research, and streaming using odds-api/odds-api. Use its GitMCP server for documentation and its native @odds-api/mcp server for live tool access when configured.
---

# Odds API Research

Two distinct integrations exist:

- `odds-api-docs`: GitMCP documentation/context for the repository.
- `odds-api-live`: native `@odds-api/mcp` server for live API tools when `ODDS_API_KEY` is configured.

## Workflow

1. Use `odds-api-docs` to confirm parameters, market names, schemas, pagination, streaming behavior, and SDK examples.
2. For actual current data, prefer `odds-api-live`. Do not treat documentation examples or mock responses as live prices.
3. Record `retrieved_at`, event ID, bookmaker, market, selection, price, line/handicap, and provider timestamp for every odds observation.
4. When comparing prices, distinguish raw bookmaker odds from fair/no-vig estimates. A missing/null fair price must remain missing.
5. For line movement, compare chronologically ordered snapshots for the same event/market/selection and avoid mixing unmatched lines.
6. For results/settlement joins, keep them in a post-event dataset; never leak them into pregame features.
7. Mock mode is for development/smoke tests only. Mark any output from mock mode as mock and never present it as current sportsbook data.
8. Treat arbitrage/positive-EV calculations as research outputs subject to stale quotes, suspended markets, limits, voids, latency, and execution risk. Do not claim guaranteed profit.

## Production defaults

- Base URL: `https://api.odds-api.net/v1`.
- Authentication: server-side `ODDS_API_KEY` / `X-API-Key`.
- Keep API keys out of client applications, logs, generated screenshots, and committed config files.

## Output contract

Return the queried event/market, source freshness, bookmakers compared, normalization assumptions, derived calculations, and any missing/suspended/stale data.
