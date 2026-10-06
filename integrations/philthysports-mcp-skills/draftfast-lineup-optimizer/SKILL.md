---
name: draftfast-lineup-optimizer
description: Build, validate, and debug DraftKings or FanDuel DFS lineup optimization workflows with BenBrostoff/draftfast. Use for salary/position rules, stacks, locks, bans, groups, custom constraints, projections, roster generation, diversification, and upload/export preparation.
---

# DraftFast Lineup Optimizer

Use `draftfast-docs` to inspect the current repository interfaces before generating code.

## Workflow

1. Identify site, sport/league, contest format, roster size, salary cap, positions, and any showdown/single-game rules.
2. Build a player pool with explicit fields: stable player ID where available, name, cost, projection, position, team, opponent/game, and status.
3. Reject players with missing salary/position data required by the selected rule set; do not invent salaries or projections.
4. Apply user constraints using the repository's supported mechanisms: locks, bans, player groups, stacks, custom rules, and no-offense-vs-defense where implemented.
5. When generating multiple lineups, add deliberate diversification/exposure rules rather than returning trivial duplicates.
6. Validate every lineup independently for salary, roster size, eligible positions, duplicate players, locks/bans, and custom constraints.
7. Keep projection generation separate from optimization. DraftFast optimizes the numbers supplied to it; it does not prove the projections are accurate.
8. If exporting for a contest platform, verify current upload schema separately before producing a production upload file.

## Environment

The repository currently documents Python 3.12+ and `pip install draftfast`.

## Output contract

Return:
- rule set/contest type;
- player-pool provenance and timestamp;
- constraints applied;
- lineup(s) with salary and projected total;
- validation results;
- unresolved late-news/injury/status risks.
