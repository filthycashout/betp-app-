# PhilthySports MCP Skill Set

Production-aligned Agent Skills collection for the six PhilthySports MCP capabilities.

## Production endpoint

`https://philthysports-mcp-v1.onrender.com/mcp`

The production MCP currently exposes governed PhilthySports tools for health/status, provider inventory, four-sport research, Best 12, Best 3 research, evidence inspection, capability inventory and explicit-input DraftFast optimization. Missing or stale production evidence fails closed; mock/test data is never silently substituted.

## Included skills

1. `sports-mcp-router` — routes PhilthySports live research, sports data, odds, DFS optimization, FanDuel research and Android/bytecode work while enforcing provenance/freshness/V8 governance.
2. `sportradar-sports-data` — works from `johnwmillr/SportradarAPIs` documentation plus authorized server-side Sportradar access.
3. `odds-api-research` — uses `odds-api/odds-api` documentation and, when configured, its native live MCP server while keeping provider credentials isolated.
4. `draftfast-lineup-optimizer` — validates DraftKings/FanDuel DFS optimizer workflows and maps to the production `philthy_dfs_optimize` tool.
5. `fanduel-api-research` — inspects the legacy unofficial Setfive FanDuel library as research-only context; no production login/account/contest automation.
6. `bytecode-viewer-analysis` — guides authorized Java/JAR/Android APK static analysis with the pinned Bytecode Viewer source and PhilthySports release-domain audit.

Each skill remains a standalone directory containing one `SKILL.md`.

## Production MCP tools

- `philthy_health`
- `philthy_system_status`
- `philthy_provider_status`
- `philthy_search`
- `philthy_best12`
- `philthy_best3`
- `philthy_evidence`
- `philthy_capability_inventory`
- `philthy_dfs_optimize`

These are analysis/research/diagnostic tools. They do not execute wagers or DFS contest entries.

## MCP configuration files

- `mcp/gitmcp-remote.json`: direct remote MCP URLs for PhilthySports plus the five GitMCP documentation servers.
- `mcp/mcp-remote-stdio.json`: `mcp-remote` command/stdio bridges for the same remote servers.
- `mcp/odds-api-native.json`: native `@odds-api/mcp` server. The PhilthySports boundary uses `ODDS_API_NET_KEY`, mapped only inside that child process to its required `ODDS_API_KEY` variable.

GitMCP endpoints provide repository documentation/context; they do not automatically execute the underlying repository or provider API. The production PhilthySports endpoint is the governed execution surface.

## Credential boundaries

- The Odds API: `THE_ODDS_API_KEY`
- odds-api.net/native MCP: `ODDS_API_NET_KEY` at PhilthySports/config boundary
- Sportradar: `SPORTRADAR_API_KEY` or provider-required sport-specific server-side keys

Do not alias credentials between providers. Never place provider secrets in the APK or committed config.

## Predictive governance

For predictive/training evidence, preserve source timestamps and enforce `as_of < event_time`. A trained model may replace the explicit market baseline only after chronology, in-fold preprocessing, OOF calibration, sample sufficiency, Brier improvement, non-inferior log loss, ECE <= 0.01, no-leakage, schema-compatibility and artifact-checksum gates pass. Use measured parlay dependence only.
