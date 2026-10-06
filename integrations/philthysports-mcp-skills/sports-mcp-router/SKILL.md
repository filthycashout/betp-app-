---
name: sports-mcp-router
description: Route sports-data, sportsbook-odds, DFS lineup optimization, FanDuel-library research, and Android/Java bytecode tasks across the configured Sportradar, Odds API, DraftFast, FanDuel API, and Bytecode Viewer MCP documentation sources. Use when a task spans two or more of these sources or the correct source is unclear.
---

# Sports MCP Router

Use this skill as the first decision layer for the requested MCP set.

## Routing rules

1. For schedules, teams, rosters, player/game statistics, transactions, or general sport-event context, consult `sportradar-docs` and use an authorized Sportradar API integration for live data.
2. For sportsbook prices, bookmaker comparison, market schemas, fair/no-vig odds, results, line movement, arbitrage research, positive-EV research, or streaming odds, prefer the native `odds-api-live` MCP when configured. Use `odds-api-docs` for contract/schema guidance.
3. For DFS lineup generation, salary/position rules, stacks, locks, bans, custom constraints, or roster exports, consult `draftfast-docs` and execute DraftFast locally when a runtime is available.
4. For the Setfive FanDuel library, use `fanduel-api-docs` for source/schema research. Do not assume the GitMCP server can log in or perform FanDuel actions. Do not make production account automation the default; the repository itself warns that its approach conflicts with FanDuel terms.
5. For JAR/APK/DEX/XAPK/APKM decompilation, bytecode/resource inspection, static search, or Java/Android reverse-engineering workflow guidance, consult `bytecode-viewer-docs` and use Bytecode Viewer locally when available.

## Multi-source sports workflow

When building a PhilthySports-style prediction or research pipeline:

1. Resolve the event identity, league, teams/players, and scheduled start time.
2. Record a provenance envelope for every observation: `source`, `retrieved_at`, `as_of`, `event_id`, and source-specific identifiers.
3. For model features or backtests, enforce `as_of < event_time` and reject settled/future information from pregame features.
4. Obtain market state from the live odds source separately from sport-stat features.
5. If DFS optimization is requested, build projections first, then pass only explicit projection/salary/position/team fields into DraftFast.
6. Keep sportsbook/DFS research outputs descriptive. Never label profit, EV, arbitrage, or a lineup as guaranteed.
7. If a source is unavailable or unauthenticated, report that source as unavailable rather than silently replacing it with fabricated/mock data unless the user explicitly requests development mock mode.

## Output contract

Return:
- sources used;
- timestamps/freshness for live inputs;
- normalized event/player identifiers;
- requested result;
- unresolved data or authentication blockers;
- whether any mock/test data was used.
