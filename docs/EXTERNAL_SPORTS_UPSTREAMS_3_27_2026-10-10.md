# External Sports Upstreams 3-27

Verified date: 2026-10-10

This integration expands the existing reproducible external-source workflow to the previously discussed GitHub repositories numbered 3 through 27.

## Invariants

- External source trees are pinned by full Git commit SHA.
- The lock manifest is the single source of truth for the sports clone workflow.
- Cloned code is an artifact for inspection, testing, comparison, and adapter development. It is not executed automatically.
- External projects do not become production authority and cannot bypass provider, chronology, leakage, calibration, promotion, credential, or signing gates.
- Credentials are never inherited from or written into cloned trees.
- Legacy or scraping-oriented projects remain reference-only unless a separate reviewed adapter explicitly promotes a narrow capability.
- `Setfive/fanduel-api` remains legacy/reference-only.
- Floot remains the production application contract; this external-source workflow does not alter routing or deployment.

## CI behavior

`clone-external-sports-repos.yml` validates that the manifest contains exactly source indexes 3-27, clones each repository at the locked SHA, verifies the checked-out commit, strips nested `.git` metadata, scans for obvious secret-bearing file names, records clone evidence, and uploads a short-lived artifact.

## Incorporation model

Prefer native/current data clients already used by PhilthyParleys (`nflreadpy`, `nba_api`, `MLB-StatsAPI`, `pybaseball`, `nhl-api-py`) for governed historical collection. Treat odds, prop, MCP, scraper, modeling, and analytics repositories as comparison/reference inputs until an explicit adapter is implemented and validated against the application's existing contracts.
