from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class SnapshotMeta:
    observed_at: datetime
    prediction_time: datetime
    event_time: datetime
    source: str


def point_in_time_valid(meta: SnapshotMeta) -> bool:
    """True only when the feature existed before prediction and event start."""

    observed = _aware(meta.observed_at)
    prediction = _aware(meta.prediction_time)
    event = _aware(meta.event_time)
    return observed <= prediction < event


def freshness_seconds(meta: SnapshotMeta) -> float:
    observed = _aware(meta.observed_at)
    prediction = _aware(meta.prediction_time)
    return max(0.0, (prediction - observed).total_seconds())


def assert_snapshot_usable(meta: SnapshotMeta, *, max_age_seconds: int) -> None:
    if not meta.source.strip():
        raise ValueError("snapshot source is required")
    if not point_in_time_valid(meta):
        raise ValueError("point-in-time invariant failed: require observed_at <= prediction_time < event_time")
    age = freshness_seconds(meta)
    if age > max_age_seconds:
        raise ValueError(f"snapshot is stale: age={age:.0f}s max={max_age_seconds}s")
