"""Unified four-sport analytics core for PhilthyParleys/Powerhouse.

This package is deliberately independent of FastAPI routing. Existing API
handlers can migrate into it incrementally without changing public contracts.
"""

SUPPORTED_SPORTS = ("MLB", "NHL", "NBA", "NFL")

__all__ = ["SUPPORTED_SPORTS"]
