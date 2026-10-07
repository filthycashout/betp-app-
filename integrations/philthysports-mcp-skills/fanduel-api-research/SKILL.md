---
name: fanduel-api-research
description: Inspect and reason about the legacy Setfive/fanduel-api TypeScript library, its models, examples, slate/lobby structures, WebSocket behavior and lineup-generator code. Use for source understanding, migration planning and schema research only. It is not a production login, sportsbook, DFS-entry or account-automation surface.
---

# FanDuel API Research

Use `fanduel-api-docs` as repository documentation/context only.

## Pinned upstream

- Repository: `Setfive/fanduel-api`
- Branch: `master`
- Verified current commit: `c4b9b746555b2f7d5b4a15a747cc82c724109db4`
- Latest upstream commit date: 2017-12-31
- PhilthySports role: `legacy_reference_only`

The age and unofficial nature of this repository are part of the evidence. Do not imply its login/session/API behavior matches current FanDuel production systems without separate current verification.

## PhilthySports production boundary

The production PhilthySports MCP at `https://philthysports-mcp-v1.onrender.com/mcp` exposes this source only through capability/routing metadata. There is no production FanDuel login, account, contest-entry or wager tool.

## Workflow

1. Determine whether the request is source/schema understanding, migration support, historical code analysis, or comparison with a current supported integration.
2. For repository research, inspect `Fanduel.ts`, `models.ts`, `examples/`, `LineupGenerator.ts` and related code through `fanduel-api-docs` before making claims.
3. Treat repository endpoints, authentication flows, WebSocket assumptions and schemas as historical until independently verified against a current authorized source.
4. Never ask the user to paste FanDuel passwords, MFA codes, session cookies or tokens into chat, source code or committed config.
5. Never store or expose account credentials through PhilthySports MCP responses.
6. Do not use this repository to bypass platform restrictions, automate login, place wagers, deposit funds or submit paid contests.
7. For DFS optimization from user-provided or authorized salary/slate data, prefer `philthy_dfs_optimize` / DraftFast rather than the legacy repository's brute-force generator.
8. When current FanDuel data is needed, use an authorized current data source and clearly separate that evidence from findings derived from this legacy repository.

## Output contract

Return the repository component inspected, exact source structure or behavior observed, pinned commit, whether the finding is historical or currently verified, unsupported/currently unknown assumptions, and the compliant alternative used for any modern production requirement.
