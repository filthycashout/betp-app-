#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
CORE = ROOT / "philthysports-mcp"
SERVICE = REPO / "backend" / "mcp_v2_service.py"
MCP_CONFIG = ROOT / "mcp" / "gitmcp-remote.json"
CORE_MCP_CONFIG = CORE / "mcp.json"
SOURCE_MAP = ROOT / "shared" / "source-map.yaml"

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
SERVICE_VERSION = "1.1.2"
BACKEND_DEFAULT = "https://philthyparleys.floot.app/_api"


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


for skill in sorted(EXPECTED_SKILLS):
    path = ROOT / skill / "SKILL.md"
    if not path.is_file():
        fail(f"missing {path.relative_to(REPO)}")
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        fail(f"{path.relative_to(REPO)} missing skill frontmatter")

for required in ("SKILL.md", "README.md", "mcp.json", "source-manifest.json", "validate.py"):
    if not (CORE / required).is_file():
        fail(f"missing core skill asset: {required}")

manifest_path = CORE / "source-manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
if manifest.get("mcp_endpoint") is not None:
    fail("standalone production MCP endpoint must remain disabled")
if manifest.get("mcp_production_enabled") is not False:
    fail("standalone production MCP must remain disabled")
if manifest.get("skill_version") != SERVICE_VERSION:
    fail("core manifest service version mismatch")
if manifest.get("backend_default") != BACKEND_DEFAULT:
    fail("core manifest backend default mismatch")
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
if f'SERVICE_VERSION = "{SERVICE_VERSION}"' not in service_text:
    fail("service version no longer matches core skill manifest; update skill set")
if f'"{BACKEND_DEFAULT}"' not in service_text:
    fail("service backend default no longer matches core skill manifest; update skill set")
if 'PUBLIC_HOST = os.getenv("MCP_PUBLIC_HOST", "").strip()' not in service_text:
    fail("MCP adapter must not have a hard-coded production host")

config = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
if "philthysports-live" in config.get("mcpServers", {}):
    fail("retired standalone PhilthySports MCP must not appear in remote config")

core_config = json.loads(CORE_MCP_CONFIG.read_text(encoding="utf-8"))
if core_config.get("mcpServers") != {}:
    fail("core MCP production connection config must remain disabled")

if not SOURCE_MAP.is_file():
    fail("shared/source-map.yaml missing")
source_map_text = SOURCE_MAP.read_text(encoding="utf-8")
for forbidden in ("onrender.com", "philthysports-mcp-v1"):
    if forbidden in source_map_text:
        fail(f"shared source map contains retired production reference: {forbidden}")
for required in (
    "production_backend:",
    f"endpoint: {BACKEND_DEFAULT}",
    "production_mcp:",
    "endpoint: null",
    "enabled: false",
    f"backend: {BACKEND_DEFAULT}",
    "wagering_execution: disabled",
):
    if required not in source_map_text:
        fail(f"shared source map missing production contract: {required}")

subprocess.run([sys.executable, str(CORE / "validate.py")], cwd=REPO, check=True)

print("PASS PhilthySports MCP skill set")
print(f"skills={len(EXPECTED_SKILLS)} tools={len(EXPECTED_TOOLS)} production_mcp=disabled backend={BACKEND_DEFAULT}")
