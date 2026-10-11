from __future__ import annotations

from collections.abc import Iterable

from .prices import implied_prob


def no_vig_two_way(a: float, b: float) -> tuple[float, float]:
    pa, pb = implied_prob(a), implied_prob(b)
    total = pa + pb
    if total <= 0:
        raise ValueError("invalid two-way market")
    return pa / total, pb / total


def no_vig_many(american_odds: Iterable[float]) -> list[float]:
    raw = [implied_prob(price) for price in american_odds]
    total = sum(raw)
    if total <= 0:
        raise ValueError("invalid market")
    return [probability / total for probability in raw]
