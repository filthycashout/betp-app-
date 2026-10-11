from __future__ import annotations

import os
from dataclasses import dataclass

from sports_ai import SUPPORTED_SPORTS


def _csv(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip().lower() for item in value.split(",") if item.strip()))


@dataclass(frozen=True)
class Settings:
    """Runtime knobs only; credentials remain environment-managed.

    No secrets file is part of the package. Deployment credentials continue to
    be injected by the production environment.
    """

    supported_sports: tuple[str, ...] = SUPPORTED_SPORTS
    min_edge: float = 0.03
    min_market_quality: float = 0.75
    max_snapshot_age_seconds: int = 900
    market_weight: float = 0.70
    kelly_fraction: float = 0.25
    sharp_book_keys: tuple[str, ...] = ("pinnacle",)
    sharp_max_age_seconds: int = 180

    @classmethod
    def from_env(cls) -> "Settings":
        value = cls(
            min_edge=float(os.getenv("SPORTS_AI_MIN_EDGE", "0.03")),
            min_market_quality=float(os.getenv("SPORTS_AI_MIN_MARKET_QUALITY", "0.75")),
            max_snapshot_age_seconds=int(os.getenv("SPORTS_AI_MAX_SNAPSHOT_AGE_SECONDS", "900")),
            market_weight=float(os.getenv("SPORTS_AI_MARKET_WEIGHT", "0.70")),
            kelly_fraction=float(os.getenv("SPORTS_AI_KELLY_FRACTION", "0.25")),
            sharp_book_keys=_csv(os.getenv("SPORTS_AI_SHARP_BOOK_KEYS", "pinnacle")),
            sharp_max_age_seconds=int(os.getenv("SPORTS_AI_SHARP_MAX_AGE_SECONDS", "180")),
        )
        value.validate()
        return value

    def validate(self) -> None:
        if not 0.0 <= self.min_edge < 1.0:
            raise ValueError("min_edge must be in [0, 1)")
        if not 0.0 <= self.min_market_quality <= 1.0:
            raise ValueError("min_market_quality must be in [0, 1]")
        if self.max_snapshot_age_seconds <= 0:
            raise ValueError("max_snapshot_age_seconds must be positive")
        if not 0.0 <= self.market_weight <= 1.0:
            raise ValueError("market_weight must be in [0, 1]")
        if not 0.0 < self.kelly_fraction <= 1.0:
            raise ValueError("kelly_fraction must be in (0, 1]")
        if self.sharp_max_age_seconds <= 0:
            raise ValueError("sharp_max_age_seconds must be positive")
        if any(not key.strip() for key in self.sharp_book_keys):
            raise ValueError("sharp_book_keys cannot contain blank values")
