---
name: sportradar-sports-data
description: Use the johnwmillr/SportradarAPIs GitMCP documentation to design or debug Python access to Sportradar schedules, teams, players, games, and statistics across supported sports. Use for Sportradar integration, endpoint discovery, normalization, rate-limit handling, and sports-data provenance.
---

# Sportradar Sports Data

Use the `sportradar-docs` GitMCP source for repository-specific classes, methods, and examples before writing integration code.

## Workflow

1. Identify the sport and requested entity: schedule, game, team, player, standings/statistics, tournament, or transaction.
2. Query repository documentation for the exact wrapper class and method names. Do not guess endpoint paths from memory.
3. Treat the wrapper as a client library, not as the data source itself. Live requests require an appropriate Sportradar API key.
4. Preserve Sportradar IDs/URNs and map them to the application's canonical IDs rather than matching only on display names.
5. Respect provider rate limits and wrapper throttling. Batch/caching logic should avoid repeated calls for immutable historical records.
6. Normalize timestamps to UTC internally; retain the provider timestamp and retrieval timestamp.
7. For predictive datasets, add `as_of` and reject records whose availability time is not strictly before the target event time.
8. If the wrapper appears stale for a specific endpoint/version, use the GitMCP repository only as implementation context and verify the current provider contract before changing production code.

## Verification

Before finalizing, state:
- sport/API family;
- wrapper method(s) used or proposed;
- required credential name/location;
- rate-limit/caching assumptions;
- source and retrieval timestamps;
- any version mismatch or unverified endpoint.
