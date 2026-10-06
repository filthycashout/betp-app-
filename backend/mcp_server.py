from __future__ import annotations

import importlib
import json
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["mcp"])
_PROTOCOL = "2025-06-18"
_SERVER = {"name": "philthysports-mcp", "version": "1.0.0"}

TOOLS = [
    {
        "name": "philthy_health",
        "description": "Return PhilthySports runtime health and deployment commit without exposing secrets.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "philthy_system_status",
        "description": "Return v8 chronology, calibration, leakage, provenance, promotion, credential and Android-signing gate status. Credential values are never returned.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "philthy_provider_status",
        "description": "Return provider configuration state and routing roles. Live provider data remains unavailable unless authenticated; no mock data is substituted.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "philthy_search",
        "description": "Run the existing PhilthySports governed search for NFL/NBA/MLB/NHL. Production evidence rules remain unchanged and unavailable live evidence fails closed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": "string"},
                "sport": {"type": "string", "enum": ["NFL", "NBA", "MLB", "NHL"]},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "include_props": {"type": "boolean", "default": False},
                "props_limit": {"type": "integer", "minimum": 0, "maximum": 20, "default": 3}
            },
            "additionalProperties": False
        },
    },
]


def _app_module():
    return importlib.import_module("app")


def _text_result(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, separators=(",", ":"), default=str)}],
        "structuredContent": payload,
        "isError": is_error,
    }


def _provider_status() -> dict[str, Any]:
    configured = {
        "sportradar": bool(os.getenv("SPORTRADAR_API_KEY", "").strip()),
        "odds_api": bool(os.getenv("ODDS_API_KEY", "").strip() or os.getenv("ODDS_API_NET_KEY", "").strip()),
    }
    return {
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "mock_data_used": False,
        "sources": {
            "sportradar": {"role": "sports_context", "authenticated": configured["sportradar"], "production": configured["sportradar"]},
            "odds_api": {"role": "live_odds", "authenticated": configured["odds_api"], "production": configured["odds_api"]},
            "draftfast": {"role": "dfs_optimizer_only", "production_sportsbook_source": False},
            "setfive_fanduel": {"role": "schema_research_only", "production": False},
            "bytecode_viewer": {"role": "authorized_static_apk_jar_dex_analysis_only", "production_data_source": False},
        },
        "predictive_contract": "as_of < event_time; fail closed on unavailable/stale evidence; no production mock substitution",
    }


def _call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    app = _app_module()
    if name == "philthy_health":
        return _text_result(app.health())
    if name == "philthy_system_status":
        return _text_result(app.system_status())
    if name == "philthy_provider_status":
        return _text_result(_provider_status())
    if name == "philthy_search":
        try:
            payload = app.search(
                q=str(args.get("q") or ""),
                sport=args.get("sport"),
                date=args.get("date"),
                include_props=bool(args.get("include_props", False)),
                props_limit=int(args.get("props_limit", 3)),
            )
            return _text_result(payload)
        except Exception as exc:
            return _text_result({"error": type(exc).__name__, "message": str(exc)}, is_error=True)
    return _text_result({"error": "unknown_tool", "tool": name}, is_error=True)


@router.get("/mcp")
def mcp_get():
    return {
        "name": _SERVER["name"],
        "version": _SERVER["version"],
        "transport": "streamable-http",
        "protocolVersion": _PROTOCOL,
        "endpoint": "/mcp",
        "mock_data_used": False,
    }


@router.post("/mcp")
async def mcp_post(request: Request):
    try:
        message = await request.json()
    except Exception:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}, status_code=400)
    if not isinstance(message, dict):
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}, status_code=400)

    request_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}
    if method == "notifications/initialized":
        return JSONResponse({}, status_code=202)
    if method == "initialize":
        result = {
            "protocolVersion": _PROTOCOL,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": _SERVER,
            "instructions": "PhilthySports governed diagnostics and sports research. Preserve source provenance, enforce as_of < event_time for predictive inputs, and never substitute mock data for production evidence.",
        }
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            arguments = {}
        result = _call_tool(name, arguments)
    elif method == "ping":
        result = {}
    else:
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}, status_code=404)
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})
