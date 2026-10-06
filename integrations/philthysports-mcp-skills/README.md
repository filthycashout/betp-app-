# PhilthySports MCP Skill Set

A reusable Agent Skills collection for the MCP/GitMCP sources requested on 2026-10-06.

## Included skills

1. `sports-mcp-router` — routes sports-data, odds, DFS optimization, FanDuel research, and APK/bytecode tasks to the right source.
2. `sportradar-sports-data` — works from the `johnwmillr/SportradarAPIs` GitMCP documentation and the Sportradar Python wrapper/API.
3. `odds-api-research` — uses `odds-api/odds-api` docs and, when configured, its native live MCP server.
4. `draftfast-lineup-optimizer` — builds/validates DraftKings or FanDuel DFS optimizer workflows with DraftFast.
5. `fanduel-api-research` — inspects the unofficial Setfive FanDuel library and schemas while keeping production use behind compliance/authorization checks.
6. `bytecode-viewer-analysis` — guides authorized Java/JAR/Android APK static analysis with Bytecode Viewer.

Each skill is a standalone directory containing exactly one `SKILL.md`, compatible with the Agent Skills format.

## MCP configuration

- `mcp/gitmcp-remote.json`: URL-based remote MCP configuration for the five GitMCP documentation servers.
- `mcp/mcp-remote-stdio.json`: `mcp-remote` configuration for clients that expect a command/stdio bridge.
- `mcp/odds-api-native.json`: the native `@odds-api/mcp` server. Requires `ODDS_API_KEY` for live data; use mock mode only for development/testing.

GitMCP is a documentation/context server for a GitHub repository. It does not automatically turn the underlying repository into executable API actions. The Odds API repository is the exception here because it also ships its own native MCP server.

## Recommended PhilthySports routing

- Pregame schedules, rosters, stats, team/player context: Sportradar.
- Current sportsbook lines, bookmaker comparison, fair/no-vig context, line movement, results: Odds API native MCP.
- DFS lineup construction and constraints: DraftFast.
- FanDuel library/API shape research: Setfive FanDuel GitMCP, with live/account automation disabled unless a compliant supported path is established.
- APK/JAR/DEX inspection, decompilation, static search, resource analysis: Bytecode Viewer.

For predictive training, retain source timestamps and enforce `as_of < event_time`; do not use settled/future information in pregame features.
