---
name: sports-mcp-router
description: Route PhilthySports live research, sports-data, sportsbook-odds, DFS optimization, FanDuel-library research, and Android/Java bytecode tasks across the production PhilthySports MCP plus the configured Sportradar, Odds API, DraftFast, FanDuel API, and Bytecode Viewer sources. Use when a task spans two or more sources or the correct source is unclear.
---

# Sports MCP Router

Use this skill as the first decision layer for the PhilthySports MCP skill set. Use `philthysports-mcp` as the primary production execution skill when the request directly targets the live PhilthySports/PhilthyParleys system.

## Production MCP

- Endpoint: `https://philthysports-mcp-v1.onrender.com/mcp`
- Current service: PhilthySports MCP v1.1.1
- Live tools: `philthy_health`, `philthy_system_status`, `philthy_provider_status`, `philthy_search`, `philthy_best12`, `philthy_best3`, `philthy_evidence`, `philthy_capability_inventory`, `philthy_dfs_optimize`.
- The production MCP delegates governed live research to the PhilthySports backend and fails closed when evidence is unavailable.

## Routing rules

1. Start with the core `philthysports-mcp` skill for live PhilthySports execution; use `philthy_health` or `philthy_provider_status` when live backend/provider availability matters.
2. For NFL/NBA/MLB/NHL schedules, games, teams, rosters, players, stats, or current research, use `philthy_search`; consult `sportradar-docs` when wrapper/API implementation details are needed.
3. For sportsbook prices, bookmaker comparison, fair/no-vig context, line movement, results, arbitrage research, positive-EV research, or streaming schemas, consult `odds-api-docs` and use authenticated live provider data only when configured. Never substitute docs/mock payloads for production prices.
4. For DFS lineup construction from explicit salary/projection inputs, use `philthy_dfs_optimize`; consult `draftfast-docs` for rule/constraint details.
5. For Setfive FanDuel source/schema research, use `fanduel-api-docs`. It remains research-only and is not a production login, account, contest-entry, or wager surface.
6. For JAR/APK/DEX/XAPK/APKM decompilation, bytecode/resource inspection, static search, or Java/Android reverse-engineering guidance, use `bytecode-viewer-docs` plus the authorized local static-analysis workflow.

## PhilthySports governance contract

1. Preserve `source`, `retrieved_at`, `as_of`, `event_id`, provider IDs, bookmaker, market, selection, line and price where applicable.
2. For predictive features and backtests, enforce `as_of < event_time`; settled/future information must not enter pregame features.
3. Market data and sports-stat/context data are separate evidence classes and must retain separate provenance.
4. A trained model may replace the explicit market baseline only after chronology, in-fold preprocessing, OOF calibration, sample sufficiency, Brier improvement, non-inferior log loss, ECE <= 0.01, no-leakage, schema compatibility and artifact-checksum gates pass.
5. Measured parlay dependence only. Missing dependence evidence must not be replaced with invented correlation.
6. Never present mock/test/example data as live production evidence.
7. Never execute wagers or DFS contest entries.
8. Keep all provider credentials server-side. Do not expose credentials through MCP results, APK code, logs or committed files.
9. Treat backend CI, APK signing, emulator smoke, live-provider proof, physical-device smoke and per-sport model promotion as separate evidence gates.

## Provider credential boundaries

Keep similarly named providers isolated. Provider secret names and values remain server-side; do not copy credentials into skill files, APK code, logs, examples or committed configuration.

## Output contract

Return the sources used, source/retrieval timestamps, normalized event/player identifiers, requested result, unresolved data/authentication blockers, model/baseline status when predictive output is involved, and whether any mock/test data was used.
