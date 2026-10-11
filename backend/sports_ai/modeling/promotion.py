from __future__ import annotations

from typing import Any


def governed_model_status(sport: str) -> dict[str, Any]:
    """Reuse the existing fail-closed v8 promotion gate instead of duplicating it."""

    from model_runtime import load_promoted, promotion_gate

    normalized = sport.upper()
    artifact = load_promoted(normalized)
    if artifact is None:
        return {
            "sport": normalized,
            "passed": False,
            "runtime_role": "BASELINE_FALLBACK",
            "checks": {},
        }
    return promotion_gate(artifact, normalized)
