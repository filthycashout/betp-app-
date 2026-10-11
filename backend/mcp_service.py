"""Compatibility entry point for the optional standalone PhilthySports MCP adapter.

Production execution now uses the canonical PhilthyParleys Floot `/_api` backend.
This module remains available only for an explicitly hosted/local MCP adapter and
imports the same implementation exercised by protocol CI.
"""
from mcp_v2_service import app, mcp

__all__ = ["app", "mcp"]
