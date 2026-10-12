from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import mean, variance
from typing import Iterable, Literal


@dataclass(frozen=True)
class CountDistribution:
    family: Literal["poisson", "negative_binomial"]
    mean: float
    variance: float
    sample_size: int
    dispersion_ratio: float
    nb_r: float | None = None
    nb_p: float | None = None


def _clean(samples: Iterable[float]) -> list[float]:
    values: list[float] = []
    for raw in samples:
        value = float(raw)
        if not math.isfinite(value) or value < 0:
            raise ValueError("count samples must be finite and non-negative")
        values.append(value)
    return values


def fit_count_distribution(
    samples: Iterable[float],
    *,
    projected_mean: float | None = None,
    minimum_samples: int = 3,
    overdispersion_threshold: float = 1.15,
) -> CountDistribution:
    """Fit a conservative count family from historical observations.

    Poisson is used when variance is near/below the mean. When sample variance
    materially exceeds the mean, method-of-moments negative binomial parameters
    are used. `projected_mean` may come from a separate role/opportunity model;
    historical dispersion is preserved around that projected mean.
    """

    values = _clean(samples)
    if len(values) < minimum_samples:
        raise ValueError(f"at least {minimum_samples} samples are required")
    historical_mean = mean(values)
    historical_variance = variance(values) if len(values) > 1 else historical_mean
    target_mean = historical_mean if projected_mean is None else float(projected_mean)
    if not math.isfinite(target_mean) or target_mean < 0:
        raise ValueError("projected_mean must be finite and non-negative")

    if historical_mean > 0:
        ratio = max(0.0, historical_variance / historical_mean)
    else:
        ratio = 1.0
    target_variance = target_mean * max(1.0, ratio)

    if target_mean <= 0 or ratio <= overdispersion_threshold or target_variance <= target_mean:
        return CountDistribution(
            family="poisson",
            mean=target_mean,
            variance=target_mean,
            sample_size=len(values),
            dispersion_ratio=ratio,
        )

    excess = target_variance - target_mean
    r = target_mean * target_mean / excess if excess > 0 else math.inf
    if not math.isfinite(r) or r <= 0:
        return CountDistribution(
            family="poisson",
            mean=target_mean,
            variance=target_mean,
            sample_size=len(values),
            dispersion_ratio=ratio,
        )
    p = r / (r + target_mean) if target_mean > 0 else 1.0
    return CountDistribution(
        family="negative_binomial",
        mean=target_mean,
        variance=target_variance,
        sample_size=len(values),
        dispersion_ratio=ratio,
        nb_r=r,
        nb_p=p,
    )


def _poisson_pmf(k: int, mu: float) -> float:
    if k < 0:
        return 0.0
    if mu == 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-mu + k * math.log(mu) - math.lgamma(k + 1))


def _nb_pmf(k: int, r: float, p: float) -> float:
    if k < 0:
        return 0.0
    if not (r > 0 and 0 < p <= 1):
        raise ValueError("invalid negative-binomial parameters")
    return math.exp(
        math.lgamma(k + r)
        - math.lgamma(r)
        - math.lgamma(k + 1)
        + r * math.log(p)
        + k * math.log1p(-p)
    )


def _pmf(k: int, distribution: CountDistribution) -> float:
    if distribution.family == "poisson":
        return _poisson_pmf(k, distribution.mean)
    assert distribution.nb_r is not None and distribution.nb_p is not None
    return _nb_pmf(k, distribution.nb_r, distribution.nb_p)


def _cdf(k: int, distribution: CountDistribution) -> float:
    if k < 0:
        return 0.0
    total = 0.0
    for value in range(k + 1):
        total += _pmf(value, distribution)
    return min(1.0, max(0.0, total))


def line_probabilities(distribution: CountDistribution, line: float) -> dict[str, float]:
    """Return win/push probabilities for over and under on a sportsbook line.

    For an integer line N: over wins at X>N, under wins at X<N, and X=N pushes.
    For non-integer lines there is no push and the integer count boundary follows
    the usual floor/ceiling interpretation.
    """

    line_value = float(line)
    if not math.isfinite(line_value) or line_value < 0:
        raise ValueError("line must be finite and non-negative")
    integer_line = line_value.is_integer()
    if integer_line:
        n = int(line_value)
        push = _pmf(n, distribution)
        under = _cdf(n - 1, distribution)
        over = max(0.0, 1.0 - _cdf(n, distribution))
    else:
        floor_line = math.floor(line_value)
        push = 0.0
        under = _cdf(floor_line, distribution)
        over = max(0.0, 1.0 - under)
    total = over + under + push
    if total > 0:
        over, under, push = over / total, under / total, push / total
    return {
        "over_win": over,
        "under_win": under,
        "push": push,
    }
