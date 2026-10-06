---
name: fanduel-api-research
description: Inspect and reason about the Setfive/fanduel-api TypeScript library, its models, examples, slate/lobby structures, WebSocket behavior, and lineup-generator code. Use for source understanding, migration planning, or schema research—not as a default production login/automation path.
---

# FanDuel API Research

Use `fanduel-api-docs` as repository documentation/context only.

## Workflow

1. Determine whether the user needs source/schema understanding, migration support, historical code analysis, or a current supported FanDuel integration.
2. For source/schema tasks, inspect `Fanduel.ts`, `models.ts`, `examples/`, and `LineupGenerator.ts` through GitMCP before proposing changes.
3. Treat the repository as unofficial. Its README explicitly warns that the approach conflicts with FanDuel terms, so do not present credential-based automation from this library as a production-safe default.
4. Never ask the user to paste account passwords into chat, source code, or committed configuration. Do not store session tokens in generated files.
5. Prefer officially supported exports/APIs or user-provided salary/slate files when building a current production pipeline.
6. For lineup optimization, prefer DraftFast unless there is a specific reason to study the repository's brute-force generator.
7. If current FanDuel behavior is required, state that the old repository may not match the modern site until verified.

## Output contract

Return:
- repository component inspected;
- data structures/endpoints inferred from source;
- whether the finding is historical or verified current;
- a compliant/current alternative when live automation is requested but unsupported.
