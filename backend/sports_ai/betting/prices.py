from __future__ import annotations


def american_to_decimal(american: float) -> float:
    if american == 0:
        raise ValueError("American odds cannot be zero")
    if american > 0:
        return 1.0 + american / 100.0
    return 1.0 + 100.0 / (-american)


def implied_prob(american: float) -> float:
    return 1.0 / american_to_decimal(american)
