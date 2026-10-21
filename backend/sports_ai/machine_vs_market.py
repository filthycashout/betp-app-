"""Independent machine-vs-market experiment ledger.

Machine predictions are frozen before market observations are admitted.
This module is intentionally independent of the wagering/EV pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Optional


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _prob(value: float) -> float:
    number = float(value)
    if not isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError("probability must be finite and between zero and one")
    return number


@dataclass(frozen=True)
class MachinePrediction:
    sport: str
    event_id: str
    target: str
    probability: float
    predicted_at: datetime
    event_starts_at: datetime
    model_version: str
    feature_cutoff_at: datetime
    market_features_used: bool = False

    def __post_init__(self) -> None:
        if not all((self.sport.strip(), self.event_id.strip(), self.target.strip(), self.model_version.strip())):
            raise ValueError("prediction identity and model version required")
        _prob(self.probability)
        if self.market_features_used:
            raise ValueError("independent predictions cannot use market-derived features")
        if not (_utc(self.feature_cutoff_at) <= _utc(self.predicted_at) < _utc(self.event_starts_at)):
            raise ValueError("feature cutoff <= prediction time < event start required")


@dataclass(frozen=True)
class MarketObservation:
    event_id: str
    target: str
    probability: float
    observed_at: datetime
    source: str

    def __post_init__(self) -> None:
        if not all((self.event_id.strip(), self.target.strip(), self.source.strip())):
            raise ValueError("market identity and source required")
        _prob(self.probability)
        _utc(self.observed_at)


@dataclass(frozen=True)
class SettledOutcome:
    event_id: str
    target: str
    actual: int
    settled_at: datetime

    def __post_init__(self) -> None:
        if self.actual not in (0, 1):
            raise ValueError("binary outcome must be 0 or 1")
        _utc(self.settled_at)


def evaluate(
    prediction: MachinePrediction,
    outcome: SettledOutcome,
    market: Optional[MarketObservation] = None,
) -> dict:
    """Compare immutable forecasts using Brier score; never use market to predict."""
    if (prediction.event_id, prediction.target) != (outcome.event_id, outcome.target):
        raise ValueError("outcome does not match prediction")
    if _utc(outcome.settled_at) <= _utc(prediction.event_starts_at):
        raise ValueError("outcome must settle after event start")
    machine_error = (prediction.probability - outcome.actual) ** 2
    result = {
        "event_id": prediction.event_id,
        "target": prediction.target,
        "model_version": prediction.model_version,
        "machine_probability": prediction.probability,
        "actual": outcome.actual,
        "machine_brier": machine_error,
        "market_probability": None,
        "market_brier": None,
        "machine_minus_market_brier": None,
    }
    if market is not None:
        if (prediction.event_id, prediction.target) != (market.event_id, market.target):
            raise ValueError("market observation does not match prediction")
        if _utc(market.observed_at) < _utc(prediction.predicted_at):
            raise ValueError("market comparison must be observed after prediction freeze")
        if _utc(market.observed_at) >= _utc(prediction.event_starts_at):
            raise ValueError("market comparison must be pregame")
        market_error = (market.probability - outcome.actual) ** 2
        result.update(
            market_probability=market.probability,
            market_brier=market_error,
            machine_minus_market_brier=machine_error - market_error,
        )
    return result
