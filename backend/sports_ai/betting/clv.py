from __future__ import annotations

from .prices import american_to_decimal


def price_clv(bet_american: float, close_american: float) -> float:
    """Positive when the ticket captured a better payout than the closing price."""

    return american_to_decimal(bet_american) / american_to_decimal(close_american) - 1.0


def probability_clv(bet_fair_prob: float, closing_fair_prob: float) -> float:
    """Movement in fair probability toward the side selected at bet time."""

    if not 0.0 <= bet_fair_prob <= 1.0 or not 0.0 <= closing_fair_prob <= 1.0:
        raise ValueError("probabilities must be in [0, 1]")
    return closing_fair_prob - bet_fair_prob
