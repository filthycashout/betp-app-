from __future__ import annotations

import math


def _clamp(probability: float) -> float:
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be in [0, 1]")
    return min(max(probability, 1e-6), 1.0 - 1e-6)


def blend_log_odds(p_market: float, p_model: float, *, w_market: float = 0.70) -> float:
    if not 0.0 <= w_market <= 1.0:
        raise ValueError("w_market must be in [0, 1]")
    market = _clamp(p_market)
    model = _clamp(p_model)
    market_logit = math.log(market / (1.0 - market))
    model_logit = math.log(model / (1.0 - model))
    z = w_market * market_logit + (1.0 - w_market) * model_logit
    return 1.0 / (1.0 + math.exp(-z))


def dynamic_market_weight(
    *,
    base_weight: float = 0.70,
    model_ece: float | None = None,
    sharp_book_count: int = 1,
    minutes_to_start: float | None = None,
) -> float:
    """Conservative market weight until enough evidence supports more model influence."""

    weight = base_weight
    if model_ece is None or model_ece > 0.01:
        weight += 0.15
    if sharp_book_count < 1:
        weight += 0.10
    elif sharp_book_count >= 2:
        weight -= 0.05
    if minutes_to_start is not None and minutes_to_start <= 30:
        weight -= 0.05
    return min(max(weight, 0.35), 0.95)
