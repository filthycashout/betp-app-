---
name: sportradar-sports-data
description: Use johnwmillr/SportradarAPIs plus the canonical PhilthyParleys Floot backend to design, debug, or consume Sportradar-backed schedules, teams, players, games, and statistics across supported sports. Use for Sportradar endpoint discovery, adapter work, normalization, rate-limit handling, freshness and sports-data provenance.
---

# Sportradar Sports Data

Use `sportradar-docs` for repository-specific classes, methods and examples. Use the PhilthyParleys Floot backend for governed live research when the server-side Sportradar adapter is configured.

## Pinned upstream

- Repository: `johnwmillr/SportradarAPIs`
- Branch: `master`
- Verified current commit: `6f15579667b6ca2dbc4bc024f8028f8c99f02dfe`
- PhilthySports lock: `integrations/upstreams.lock.json`

Do not silently float to another commit during reproducible validation.

## Production surfaces

- Backend: `https://philthyparleys.floot.app/_api`
- `/v1/data/providers` and `/v1/providers/canary`: inspect safe provider/routing status without exposing credentials.
- `/v1/search`: consume governed NFL/NBA/MLB/NHL research returned by the live backend.
- evidence routes: inspect captured source/provenance evidence.
- `/v1/system/status`: inspect production evidence/model gate state.
- The standalone production MCP HTTP endpoint is disabled.

## Workflow

1. Identify the sport and requested entity: schedule, game, team, player, standings/statistics, tournament or transaction.
2. For implementation work, query `sportradar-docs` for the exact wrapper class and method names. Do not guess endpoint paths from memory.
3. Treat the wrapper as a client library, not the data source itself. Live requests require an authorized server-side Sportradar credential.
4. Keep `SPORTRADAR_API_KEY` or any sport-specific credential server-side. Never put it in the APK, response payloads, committed configuration or logs.
5. Preserve Sportradar IDs/URNs and map them to the application's canonical IDs rather than matching only on display names.
6. Respect provider rate limits and wrapper throttling. Cache immutable historical records where appropriate and avoid redundant live calls.
7. Normalize timestamps to UTC internally while retaining provider and retrieval timestamps.
8. For predictive datasets, add `as_of` and reject records whose availability time is not strictly before the target event time.
9. If the wrapper is stale for an endpoint/version, keep it as implementation context only and verify the current Sportradar provider contract before changing production code.
10. Sportradar context cannot bypass PhilthySports model-promotion gates; unpromoted sports remain on the explicit market baseline.

## Verification

Before finalizing, report the sport/API family, wrapper method(s) used or proposed, credential boundary, provider/source IDs, rate-limit/caching assumptions, source and retrieval timestamps, any version mismatch, and any live endpoint that was not actually verified.
