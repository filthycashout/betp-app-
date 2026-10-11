---
name: philthysports-mcp
description: Operate the canonical PhilthyParleys Floot backend as the governed execution layer for NFL/NBA/MLB/NHL research, Best 12/Best 3 analysis, provider diagnostics, v8 evidence/gate inspection, and explicit-input DFS optimization. Use whenever a request targets the live PhilthySports/PhilthyParleys system rather than only one supporting repository.
---

# PhilthySports MCP

Use this skill for the governed PhilthySports/PhilthyParleys execution contract. Production execution is now provided by the single Floot backend; the standalone MCP HTTP service is disabled unless an operator explicitly hosts the local adapter.

## Production service

- Canonical backend: `https://philthyparleys.floot.app/_api`
- Standalone production MCP endpoint: disabled
- Local/explicit-host MCP adapter name: `philthysports-mcp`
- Service version: `1.1.2`
- Sports: NFL, NBA, MLB, NHL
- Production transport: HTTPS JSON through Floot `/_api`
- Optional MCP adapter transport: Streamable HTTP only when `MCP_PUBLIC_HOST` is explicitly configured

## MCP adapter tools

- `philthy_health`
- `philthy_system_status`
- `philthy_provider_status`
- `philthy_search`
- `philthy_best12`
- `philthy_best3`
- `philthy_evidence`
- `philthy_capability_inventory`
- `philthy_dfs_optimize`

## Governance contract

1. Preserve provenance and freshness returned by the service: `source`, `retrieved_at`, `as_of`, event/provider identifiers and bookmaker/market identifiers when present.
2. For predictive evidence enforce `as_of < event_time`.
3. Never silently replace unavailable live/production evidence with mock, sample, synthetic, stale or test data.
4. Never invent missing odds, player props, injuries, projections, salaries, historical rows, model metrics, credentials or settled results.
5. Keep the explicit market baseline active unless the relevant sport has actually passed the v8 promotion gates.
6. Treat provider configuration and live credential proof as separate states. A configured credential is not proof of a successful fresh credentialed response.
7. A green CI build, signed APK, emulator launch, live-provider proof, physical-device smoke and four-sport model promotion are separate claims.
8. Never expose API keys, tokens, signing material or credential values in tool output, logs, skill files or APK code.
9. Do not execute wagers or DFS contest entries.
10. Setfive/FanDuel remains research-only. Bytecode Viewer remains authorized static APK/JAR/DEX analysis only.

## Tool routing

### `philthy_health`
Use to separate backend reachability from provider/data failures. A healthy `/health` endpoint does not by itself prove live props, model promotion or release readiness.

### `philthy_system_status`
Use for chronology, calibration, leakage, provenance, credential, Android-signing and model-promotion gates. Preserve exact PASS/FAIL/BLOCKED/NOT-RUN style state from the backend.

### `philthy_provider_status`
Use for provider inventory and provider-routing diagnostics. Distinguish configured providers from fresh credentialed provider responses.

### `philthy_search`
Use for governed NFL/NBA/MLB/NHL live research. Narrow by sport/date when supplied. Set `include_props=true` only when props are relevant and keep `props_limit` small unless broader coverage is requested.

### `philthy_best12`
Use for strongest/ranked PhilthySports plays. Never fill missing evidence with fabricated picks.

### `philthy_best3`
Use for governed three-leg parlay research only. Preserve dependence/correlation warnings and do not submit a wager.

### `philthy_evidence`
Use when the user asks why a result should be trusted, when provenance/freshness matters, or when verifying that evidence existed before an event.

### `philthy_capability_inventory`
Use to inspect the incorporated supporting roles: routing, Sportradar, Odds API, DraftFast, FanDuel research and Bytecode Viewer analysis.

### `philthy_dfs_optimize`
Use only with explicit player data. Every player must provide `name`, `cost`, `proj`, and `pos`; optional fields are `team` and `matchup`. Do not invent missing salaries/projections.

Supported optimizer rule sets:
- DraftKings: NFL, NBA, MLB, NHL
- FanDuel: NFL, NBA, MLB

## Recommended workflows

### Current matchup research
1. Use the canonical Floot `/_api/v1/search` route, or the local adapter's `philthy_search` when explicitly hosted.
2. Use evidence routes when verification/provenance is requested.
3. Use system status if the answer depends on whether the output is market-baseline or promoted-model driven.

### Player props
1. Use provider status.
2. Use governed search with `include_props=true`, or `/_api/v1/game/props` for one event.
3. Require fresh returned evidence.
4. If provider credentials are merely configured but no successful credentialed response is verified, report props as blocked/unverified instead of substituting another source silently.

### Best plays / parlays
1. Use the Best 12/Best 3 governed routes or adapter tools.
2. Verify top selections with evidence when requested.
3. Preserve model/baseline state and dependence warnings.

### Production readiness
Use system status. Report backend health, live-provider proof, immutable evidence, per-sport model promotion, APK signing/emulator evidence and physical-device smoke as separate gates.

## Strict model-promotion rule

A trained sport model may replace the market baseline only after the existing PhilthySports v8 policy passes chronology, in-fold preprocessing, walk-forward OOF evidence, OOF-only calibration, sample sufficiency, Brier improvement, non-inferior log loss, ECE <= 0.01, leakage audit, schema compatibility, provenance/checksum requirements, signed portable artifact validation and required mobile parity. Never lower a threshold merely to obtain promotion.

## Failure behavior

- `UNAVAILABLE`: report source/status/error and do not fabricate the missing result.
- `INVALID_ARGUMENT`: correct the arguments.
- `UNSUPPORTED_RULE_SET`: report supported DFS combinations.
- `INVALID_PLAYER`: report the missing explicit player fields.
- `NO_FEASIBLE_LINEUP`: report that the supplied pool/constraints produced no legal lineup.
- provider/gate blocked: preserve the backend blocker and minimum remediation.

Retryable 429/502/503/504 conditions may be retried by the service; do not loop indefinitely from the skill layer.

## Supporting skills

Use these only when their specialized source/implementation context is needed:

- `sports-mcp-router`
- `sportradar-sports-data`
- `odds-api-research`
- `draftfast-lineup-optimizer`
- `fanduel-api-research`
- `bytecode-viewer-analysis`

The canonical PhilthyParleys Floot API is the governed production execution surface. GitMCP endpoints and the local MCP adapter are documentation/development surfaces unless explicitly configured outside production.
