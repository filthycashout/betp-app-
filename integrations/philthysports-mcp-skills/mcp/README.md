# MCP connection files

`gitmcp-remote.json` contains direct remote MCP URLs for the production PhilthySports MCP plus the five GitMCP documentation servers.

`mcp-remote-stdio.json` wraps those remote MCP URLs with `npx mcp-remote` for clients that expect a local command/stdio entry.

`odds-api-native.json` starts the `odds-api/odds-api` native MCP server with `npx @odds-api/mcp`. Supply `ODDS_API_NET_KEY` at the PhilthySports/config boundary; the launch file maps it only inside that child process to the package-required `ODDS_API_KEY` environment variable.

Keep The Odds API credentials separate as `THE_ODDS_API_KEY`. Do not alias or reuse the two providers' keys.

Production PhilthySports MCP endpoint:

`https://philthysports-mcp-v1.onrender.com/mcp`

GitMCP endpoints provide repository documentation/context. They do not automatically execute the underlying repository code or provider API. The PhilthySports production MCP is the governed execution surface and does not execute wagers or DFS contest entries.
