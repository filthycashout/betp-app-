# PhilthySports MCP Skill Pack

This directory is the primary production execution skill for the deployed PhilthySports MCP.

## Endpoint

`https://philthysports-mcp-v1.onrender.com/mcp`

## Included

- `SKILL.md` — production routing, evidence, provider, model-governance and DFS instructions.
- `mcp.json` — generic Streamable HTTP MCP connection configuration.
- `source-manifest.json` — source/version/tool provenance for the skill.
- `validate.py` — structural validation of the local skill pack.

The production MCP is the governed execution surface for NFL/NBA/MLB/NHL research, diagnostics, evidence inspection, Best 12/Best 3 analysis and explicit-input DFS optimization. Supporting GitMCP endpoints are documentation/context surfaces unless separately configured for execution.

The skill must fail closed when live evidence is unavailable. It must preserve `as_of < event_time`, keep provider secrets server-side, distinguish configured credentials from verified live-provider proof, and never execute wagers or DFS contest entries.
