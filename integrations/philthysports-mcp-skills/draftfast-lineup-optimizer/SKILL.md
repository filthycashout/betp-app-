---
name: draftfast-lineup-optimizer
description: Build, validate and debug DraftKings or FanDuel DFS lineup optimization workflows with BenBrostoff/draftfast and the PhilthySports production MCP. Use for salary/position rules, locks, bans, projections, explicit-input roster generation, constraints, diversification and validation. Never use it to enter contests automatically.
---

# DraftFast Lineup Optimizer

Use `draftfast-docs` for repository interfaces and `philthy_dfs_optimize` for the production PhilthySports MCP optimizer surface.

## Pinned upstream

- Repository: `BenBrostoff/draftfast`
- Branch: `master`
- Verified current commit: `0f5f1f2eb6e2ba7cb4cb6813ee36a3a079369a9b`
- PhilthySports lock: `integrations/upstreams.lock.json`
- Runtime package currently used by MCP: `draftfast==3.12.5`

## Production MCP

Endpoint: `https://philthysports-mcp-v1.onrender.com/mcp`

`philthy_dfs_optimize` currently supports these rule sets:

- DraftKings NFL, NBA, MLB, NHL
- FanDuel NFL, NBA, MLB

FanDuel NHL is not exposed by the current MCP rule map and must not be claimed as supported until implemented and tested.

## Required player input

Each player must include:

- `name`
- `cost`
- `proj`
- `pos`

Optional fields include `team` and `matchup`. The MCP rejects missing required fields and duplicate player/position/team entries rather than inventing values.

## Workflow

1. Identify site, sport/league, contest format, roster size, salary cap and position rules.
2. Build the player pool from evidence with explicit salary, position and projection values; never fabricate missing salaries, status or projections.
3. Preserve player-pool provenance and retrieval time outside the optimizer because DraftFast only optimizes the values supplied to it.
4. Apply explicit locks/bans only from the caller's request or verified lineup policy.
5. Validate the returned lineup for rule set, roster size, position eligibility, salary, duplicates and requested locks/bans.
6. Treat `projection_accuracy_verified=false` as meaningful: optimization success does not validate projection quality.
7. If generating multiple lineups outside the current single-lineup MCP tool, implement and verify diversification/exposure rules separately.
8. Verify any contest-upload schema separately before producing an upload file.
9. Never submit a lineup, enter a paid contest, deposit funds or automate account actions through this skill.

## Output contract

Return site/sport/rule set, player-pool provenance/timestamp, constraints applied, lineup members, salary total, projected total, validation status, projection-verification status, late-news/injury risks and whether contest entry was executed (it must remain false for this MCP).
