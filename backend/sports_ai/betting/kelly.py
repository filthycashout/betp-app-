from __future__ import annotations

from .prices import american_to_decimal


def fractional_kelly(probability: float, american: float, *, fraction: float = 0.25) -> float:
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be in [0, 1]")
    if not 0.0 < fraction <= 1.0:
        raise ValueError("fraction must be in (0, 1]")
    decimal = american_to_decimal(american)
    b = decimal - 1.0
    full_kelly = (probability * b - (1.0 - probability)) / b
    return max(0.0, full_kelly * fraction)
