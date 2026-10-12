from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from statistics import mean
from typing import Iterable, Literal

from sports_ai.betting.prices import american_to_decimal
from sports_ai.props.distributions import fit_count_distribution, line_probabilities


@dataclass(frozen=True)
class RateEstimate:
    rate_per_opportunity: float
    sample_size: int
    total_stat: float
    total_opportunity: float
    average_opportunity: float


def _values(items: Iterable[float], *, name: str) -> list[float]:
    out: list[float] = []
    for raw in items:
        value = float(raw)
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must contain finite non-negative values")
        out.append(value)
    return out


def estimate_rate(
    stat_samples: Iterable[float],
    opportunity_samples: Iterable[float],
    *,
    minimum_samples: int = 3,
) -> RateEstimate:
    stats = _values(stat_samples, name="stat_samples")
    opportunities = _values(opportunity_samples, name="opportunity_samples")
    if len(stats) != len(opportunities):
        raise ValueError("stat and opportunity samples must have the same length")
    if len(stats) < minimum_samples:
        raise ValueError(f"at least {minimum_samples} paired samples are required")
    total_opportunity = sum(opportunities)
    if total_opportunity <= 0:
        raise ValueError("total opportunity must be positive")
    return RateEstimate(
        rate_per_opportunity=sum(stats) / total_opportunity,
        sample_size=len(stats),
        total_stat=sum(stats),
        total_opportunity=total_opportunity,
        average_opportunity=mean(opportunities),
    )


def _push_aware_ev(win_probability: float, push_probability: float, american_odds: float) -> float:
    decimal = american_to_decimal(american_odds)
    loss_probability = max(0.0, 1.0 - win_probability - push_probability)
    return win_probability * (decimal - 1.0) - loss_probability


def project_count_prop(
    *,
    stat_samples: Iterable[float],
    opportunity_samples: Iterable[float],
    projected_opportunity: float,
    line: float,
    side: Literal["over", "under"],
    american_odds: float | None = None,
    minimum_samples: int = 3,
) -> dict[str, object]:
    """Produce an uncalibrated research probability from role -> rate -> count model.

    This function deliberately cannot promote itself into a recommendation. Its
    output carries `RESEARCH_UNCALIBRATED` and `recommendation_eligible=False`;
    an OOF calibration/promotion layer must wrap it before use in live picks.
    """

    if side not in {"over", "under"}:
        raise ValueError("side must be over or under")
    opportunity = float(projected_opportunity)
    if not math.isfinite(opportunity) or opportunity < 0:
        raise ValueError("projected_opportunity must be finite and non-negative")

    stat_values = _values(stat_samples, name="stat_samples")
    opportunity_values = _values(opportunity_samples, name="opportunity_samples")
    rate = estimate_rate(stat_values, opportunity_values, minimum_samples=minimum_samples)
    projected_mean = rate.rate_per_opportunity * opportunity
    distribution = fit_count_distribution(
        stat_values,
        projected_mean=projected_mean,
        minimum_samples=minimum_samples,
    )
    probabilities = line_probabilities(distribution, line)
    win_probability = probabilities["over_win"] if side == "over" else probabilities["under_win"]
    push_probability = probabilities["push"]
    expected_value = None
    if american_odds is not None:
        expected_value = _push_aware_ev(win_probability, push_probability, float(american_odds))

    return {
        "status": "RESEARCH_UNCALIBRATED",
        "calibrated": False,
        "promotion_passed": False,
        "recommendation_eligible": False,
        "rate": asdict(rate),
        "projected_opportunity": opportunity,
        "projected_mean": projected_mean,
        "distribution": asdict(distribution),
        "line": float(line),
        "side": side,
        "win_probability": win_probability,
        "push_probability": push_probability,
        "loss_probability": max(0.0, 1.0 - win_probability - push_probability),
        "research_expected_value": expected_value,
        "governance_reason": "OOF_CALIBRATION_AND_MODEL_PROMOTION_REQUIRED",
    }
