#!/usr/bin/env python3
from pathlib import Path
import json

root = Path(__file__).resolve().parent
required = ["SKILL.md", "README.md", "mcp.json", "source-manifest.json"]
missing = [name for name in required if not (root / name).exists()]
if missing:
    raise SystemExit("FAIL missing: " + ", ".join(missing))

skill = (root / "SKILL.md").read_text(encoding="utf-8")
manifest = json.loads((root / "source-manifest.json").read_text(encoding="utf-8"))
mcp = json.loads((root / "mcp.json").read_text(encoding="utf-8"))

endpoint = "https://philthysports-mcp-v1.onrender.com/mcp"
tools = [
    "philthy_health",
    "philthy_system_status",
    "philthy_provider_status",
    "philthy_search",
    "philthy_best12",
    "philthy_best3",
    "philthy_evidence",
    "philthy_capability_inventory",
    "philthy_dfs_optimize",
]

assert mcp["mcpServers"]["philthysports"]["url"] == endpoint
assert manifest["mcp_endpoint"] == endpoint
assert manifest["skill_version"] == "1.1.2"
assert manifest["backend_default"] == "https://philthyparleys.floot.app/_api"
assert manifest["transport"] == "streamable-http"
assert "as_of < event_time" in skill
assert "Never silently replace" in skill
assert "Do not execute wagers" in skill
for tool in tools:
    assert tool in skill, f"missing SKILL tool: {tool}"
    assert tool in manifest["tools"], f"missing manifest tool: {tool}"

print("PASS PhilthySports MCP skill pack")
print("endpoint=" + endpoint)
print("version=" + manifest["skill_version"])
print("tools=" + str(len(tools)))
