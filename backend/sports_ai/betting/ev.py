from __future__ import annotations

from .prices import american_to_decimal


def expected_value(probability: float, american: float) -> float:
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be in [0, 1]")
    decimal = american_to_decimal(american)
    return probability * (decimal - 1.0) - (1.0 - probability)
