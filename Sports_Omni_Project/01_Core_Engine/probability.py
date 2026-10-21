from __future__ import annotations
from collections.abc import Sequence

def american_to_implied_probability(odds: int | float) -> float:
    value=float(odds)
    if value == 0: raise ValueError("American odds cannot be zero")
    return abs(value)/(abs(value)+100.0) if value < 0 else 100.0/(value+100.0)

def implied_probability_to_american(probability: float) -> int:
    p=float(probability)
    if not 0.0 < p < 1.0: raise ValueError("probability must be strictly between 0 and 1")
    return int(round(-100*p/(1-p) if p >= 0.5 else 100*(1-p)/p))

def devig_two_way(odds_a: int | float, odds_b: int | float) -> tuple[float,float]:
    a,b=american_to_implied_probability(odds_a),american_to_implied_probability(odds_b)
    total=a+b
    if total <= 0: raise ValueError("invalid implied probability total")
    return a/total,b/total

def independent_parlay_probability(probabilities: Sequence[float]) -> float:
    result=1.0
    for value in probabilities:
        p=float(value)
        if not 0 <= p <= 1: raise ValueError("probabilities must be in [0, 1]")
        result*=p
    return result
