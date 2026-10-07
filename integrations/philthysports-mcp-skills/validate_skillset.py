#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
CORE = ROOT / "philthysports-mcp"
SERVICE = REPO / "backend" / "mcp_v2_service.py"
MCP_CONFIG = ROOT / "mcp" / "gitmcp-remote.json"

EXPECTED_SKILLS = {
    "philthysports-mcp",
    "sports-mcp-router",
    "sportradar-sports-data",
    "odds-api-research",
    "draftfast-lineup-optimizer",
    "fanduel-api-research",
    "bytecode-viewer-analysis",
}
EXPECTED_TOOLS = [
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
ENDPOINT = "https://philthysports-mcp-v1.onrender.com/mcp"


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


for skill in sorted(EXPECTED_SKILLS):
    path = ROOT / skill / "SKILL.md"
    if not path.is_file():
        fail(f"missing {path.relative_to(REPO)}")
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        fail(f"{path.relative_to(REPO)} missing skill frontmatter")

manifest_path = CORE / "source-manifest.json"
if not manifest_path.is_file():
    fail("missing core source-manifest.json")
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
if manifest.get("mcp_endpoint") != ENDPOINT:
    fail("core manifest endpoint mismatch")
if manifest.get("tools") != EXPECTED_TOOLS:
    fail("core manifest tool inventory mismatch")
if set(manifest.get("supporting_skills", [])) != EXPECTED_SKILLS - {"philthysports-mcp"}:
    fail("supporting skill inventory mismatch")

core_text = (CORE / "SKILL.md").read_text(encoding="utf-8")
for tool in EXPECTED_TOOLS:
    if tool not in core_text:
        fail(f"core SKILL.md missing tool {tool}")
for contract in (
    "as_of < event_time",
    "Never silently replace",
    "Do not execute wagers or DFS contest entries",
    "configured credential is not proof",
):
    if contract not in core_text:
        fail(f"core SKILL.md missing governance contract: {contract}")

if not SERVICE.is_file():
    fail("backend/mcp_v2_service.py missing")
service_text = SERVICE.read_text(encoding="utf-8")
for tool in EXPECTED_TOOLS:
    if f"def {tool}(" not in service_text:
        fail(f"service implementation missing {tool}")
if 'SERVICE_VERSION = "1.1.1"' not in service_text:
    fail("service version no longer matches core skill manifest; update skill set")

config = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
if config.get("mcpServers", {}).get("philthysports-live", {}).get("url") != ENDPOINT:
    fail("MCP connection config endpoint mismatch")

print("PASS PhilthySports MCP skill set")
print(f"skills={len(EXPECTED_SKILLS)} tools={len(EXPECTED_TOOLS)} endpoint={ENDPOINT}")
