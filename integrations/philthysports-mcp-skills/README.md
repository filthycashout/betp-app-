# PhilthySports MCP Skill Set

Production-aligned Agent Skills collection for the PhilthySports MCP core execution skill plus six supporting capability skills.

## Production endpoint

`https://philthysports-mcp-v1.onrender.com/mcp`

The production MCP currently exposes governed PhilthySports tools for health/status, provider inventory, four-sport research, Best 12, Best 3 research, evidence inspection, capability inventory and explicit-input DraftFast optimization. Missing or stale production evidence fails closed; mock/test data is never silently substituted.

## Included skills

1. `philthysports-mcp` — primary production execution skill. Routes the nine live MCP tools, preserves v8 gate semantics, distinguishes configured providers from verified live-provider proof, and keeps APK/emulator/physical-device/model-promotion evidence separate.
2. `sports-mcp-router` — routes PhilthySports live research, sports data, odds, DFS optimization, FanDuel research and Android/bytecode work while enforcing provenance/freshness/v8 governance.
3. `sportradar-sports-data` — works from `johnwmillr/SportradarAPIs` documentation plus authorized server-side Sportradar access.
4. `odds-api-research` — uses `odds-api/odds-api` documentation and, when configured, its native live MCP server while keeping provider credentials isolated.
5. `draftfast-lineup-optimizer` — validates DraftKings/FanDuel DFS optimizer workflows and maps to the production `philthy_dfs_optimize` tool.
6. `fanduel-api-research` — inspects the legacy unofficial Setfive FanDuel library as research-only context; no production login/account/contest automation.
7. `bytecode-viewer-analysis` — guides authorized Java/JAR/Android APK static analysis with the pinned Bytecode Viewer source and PhilthySports release-domain audit.

Every skill directory contains a `SKILL.md`. The primary `philthysports-mcp` directory additionally includes `source-manifest.json` so the skill can be checked against the production service implementation.

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
- `mcp/odds-api-native.json`: native `@odds-api/mcp` server. Keep its provider credential isolated from other odds providers.

GitMCP endpoints provide repository documentation/context; they do not automatically execute the underlying repository or provider API. The production PhilthySports endpoint is the governed execution surface.

## Evidence boundaries

- Provider credentials remain server-side and are never committed into a skill, APK or MCP result.
- A provider being configured is not equivalent to a successful fresh credentialed response.
- A green backend/Android CI run is not equivalent to physical-device evidence.
- Emulator evidence must never be reported as a physical-phone pass.
- Historical/training evidence must preserve source timestamps and satisfy `as_of < event_time`.
- Synthetic/random notebook values are not admissible canonical training evidence.

## Predictive governance

For predictive/training evidence, preserve source timestamps and enforce `as_of < event_time`. A trained model may replace the explicit market baseline only after chronology, in-fold preprocessing, walk-forward OOF evidence, OOF-only calibration, sample sufficiency, Brier improvement, non-inferior log loss, ECE <= 0.01, no-leakage, schema compatibility, provenance/checksum requirements, signed portable artifact validation and required mobile parity pass. Use measured parlay dependence only.

## Validation

Run:

```bash
python integrations/philthysports-mcp-skills/validate_skillset.py
```

The validator checks the seven skill directories, the nine documented live tools, endpoint alignment and the core source manifest.
