# PhilthySports MCP Skill Set

Production-aligned Agent Skills collection for the PhilthySports core execution contract plus six supporting capability skills.

## Production backend

`https://philthyparleys.floot.app/_api`

The Floot backend is the single governed production execution surface. The former standalone production MCP endpoint is disabled; the MCP adapter remains local or explicit-host only.

## Included skills

1. `philthysports-mcp` — primary production execution contract. Routes the nine adapter tools when explicitly hosted, preserves v8 gate semantics, distinguishes configured providers from verified live-provider proof, and keeps APK/emulator/physical-device/model-promotion evidence separate.
2. `sports-mcp-router` — routes PhilthySports live research, sports data, odds, DFS optimization, FanDuel research and Android/bytecode work while enforcing provenance/freshness/v8 governance.
3. `sportradar-sports-data` — works from `johnwmillr/SportradarAPIs` documentation plus authorized server-side Sportradar access.
4. `odds-api-research` — uses `odds-api/odds-api` documentation and, when configured, its native live MCP server while keeping provider credentials isolated.
5. `draftfast-lineup-optimizer` — validates DraftKings/FanDuel DFS optimizer workflows and maps to the optional `philthy_dfs_optimize` adapter tool.
6. `fanduel-api-research` — inspects the legacy unofficial Setfive FanDuel library as research-only context; no production login/account/contest automation.
7. `bytecode-viewer-analysis` — guides authorized Java/JAR/Android APK static analysis with the pinned Bytecode Viewer source and PhilthySports release-domain audit.

Every skill directory contains a `SKILL.md`. The primary `philthysports-mcp` directory additionally includes `source-manifest.json` so the skill can be checked against the adapter implementation and canonical Floot backend contract.

## Optional MCP adapter tools

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

- `mcp/gitmcp-remote.json`: direct remote URLs for the five GitMCP documentation servers; the retired PhilthySports standalone production MCP is absent.
- `mcp/mcp-remote-stdio.json`: `mcp-remote` command/stdio bridges for those documentation servers.
- `mcp/odds-api-native.json`: native `@odds-api/mcp` server. Keep its provider credential isolated from other odds providers.

GitMCP endpoints provide repository documentation/context; they do not automatically execute the underlying repository or provider API. The Floot `/_api` backend is the governed application execution surface.

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

The validator checks the seven skill directories, the nine documented adapter tools, single-backend alignment and the core source manifest.
