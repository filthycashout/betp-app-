"""Register the governed PhilthySports MCP router on FastAPI apps in this backend.

Render starts ``uvicorn app:app`` from this directory. Python imports
``sitecustomize`` during interpreter startup, so this keeps the existing start
command and production application behavior intact while adding only /mcp.
"""
from __future__ import annotations

try:
    from fastapi import FastAPI
    from mcp_server import router as philthy_mcp_router
except Exception:
    FastAPI = None
    philthy_mcp_router = None

if FastAPI is not None and philthy_mcp_router is not None and not getattr(FastAPI, "_philthy_mcp_registered", False):
    _original_init = FastAPI.__init__

    def _philthy_init(self, *args, **kwargs):
        _original_init(self, *args, **kwargs)
        self.include_router(philthy_mcp_router)

    FastAPI.__init__ = _philthy_init
    FastAPI._philthy_mcp_registered = True
