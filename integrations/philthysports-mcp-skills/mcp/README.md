# MCP connection files

`gitmcp-remote.json` is for clients that accept remote MCP URLs directly.

`mcp-remote-stdio.json` wraps each GitMCP URL with `npx mcp-remote` for clients that expect a local command/stdio entry.

`odds-api-native.json` starts the repository's native Odds API MCP server with `npx @odds-api/mcp`. Keep `ODDS_API_KEY` in the environment; do not commit a real key into this file.

GitMCP endpoints provide repository documentation/context. They do not automatically execute the underlying repository code or provider API.
