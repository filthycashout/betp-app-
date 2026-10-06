"""Compatibility entry point for the standalone PhilthySports MCP v2 service.

Render starts `mcp_service:app`; the implementation lives in
`mcp_v2_service.py` so protocol CI can import and exercise the same server.
"""
from mcp_v2_service import app, mcp

__all__ = ["app", "mcp"]
