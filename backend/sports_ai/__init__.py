"""Unified five-sport analytics core for PhilthyParleys/Powerhouse.

This package is deliberately independent of FastAPI routing. Existing API
handlers can migrate into it incrementally without changing public contracts.
"""

SUPPORTED_SPORTS = ("NFL", "NBA", "MLB", "NHL", "UFC")

__all__ = ["SUPPORTED_SPORTS"]
