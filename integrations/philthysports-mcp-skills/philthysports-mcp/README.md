# PhilthySports MCP Skill Pack

This directory defines the governed PhilthySports/PhilthyParleys execution contract and optional MCP adapter.

## Production backend

`https://philthyparleys.floot.app/_api`

The former standalone production MCP endpoint is disabled. `backend/mcp_v2_service.py` remains available only as a local or explicitly hosted adapter; it has no hard-coded public production host.

## Included

- `SKILL.md` — production routing, evidence, provider, model-governance and DFS instructions.
- `mcp.json` — production MCP connection configuration; intentionally empty while the standalone endpoint is disabled.
- `source-manifest.json` — source/version/tool provenance for the skill.
- `validate.py` — structural validation of the local skill pack.

The Floot backend is the governed production execution surface for NFL/NBA/MLB/NHL research, diagnostics, evidence inspection and application-facing analysis. Supporting GitMCP endpoints are documentation/context surfaces unless separately configured for execution.

The skill must fail closed when live evidence is unavailable. It must preserve `as_of < event_time`, keep provider secrets server-side, distinguish configured credentials from verified live-provider proof, and never execute wagers or DFS contest entries.
