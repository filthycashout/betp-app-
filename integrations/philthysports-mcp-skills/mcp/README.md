# MCP connection files

`gitmcp-remote.json` contains remote URLs for the five GitMCP documentation servers. The retired standalone PhilthySports production MCP is intentionally absent.

`mcp-remote-stdio.json` wraps those documentation MCP URLs with `npx mcp-remote` for clients that expect a local command/stdio entry.

`odds-api-native.json` starts the `odds-api/odds-api` native MCP server with `npx @odds-api/mcp`. Supply `ODDS_API_NET_KEY` at the PhilthySports/config boundary; the launch file maps it only inside that child process to the package-required `ODDS_API_KEY` environment variable.

Keep The Odds API credentials separate as `THE_ODDS_API_KEY`. Do not alias or reuse the two providers' keys.

Canonical PhilthyParleys production backend:

`https://philthyparleys.floot.app/_api`

GitMCP endpoints provide repository documentation/context. They do not automatically execute the underlying repository code or provider API. The Floot backend is the governed application execution surface and does not execute wagers or DFS contest entries. The local MCP adapter may be hosted only when an operator explicitly supplies its host configuration.
