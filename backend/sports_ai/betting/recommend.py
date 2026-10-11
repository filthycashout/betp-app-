from __future__ import annotations

from dataclasses import dataclass

from .ev import expected_value
from .kelly import fractional_kelly


@dataclass(frozen=True)
class RecommendationInput:
    probability: float
    american_odds: float
    edge: float
    snapshot_age_seconds: float
    market_quality: float
    source_health_passed: bool
    context_ready: bool
    model_contributed: bool = False
    model_promotion_passed: bool = False
    dependence_required: bool = False
    dependence_available: bool = False
    require_sharp_anchor: bool = False
    sharp_anchor_verified: bool = False


@dataclass(frozen=True)
class RecommendationDecision:
    eligible: bool
    reasons: tuple[str, ...]
    ev: float
    kelly_fraction: float


def evaluate(
    item: RecommendationInput,
    *,
    min_edge: float,
    min_market_quality: float,
    max_snapshot_age_seconds: int,
    kelly_fraction: float,
) -> RecommendationDecision:
    value = expected_value(item.probability, item.american_odds)
    reasons: list[str] = []

    if item.edge < min_edge:
        reasons.append("EDGE_BELOW_THRESHOLD")
    if value <= 0.0:
        reasons.append("NON_POSITIVE_EV")
    if item.snapshot_age_seconds > max_snapshot_age_seconds:
        reasons.append("STALE_SNAPSHOT")
    if item.market_quality < min_market_quality:
        reasons.append("LOW_MARKET_QUALITY")
    if not item.source_health_passed:
        reasons.append("SOURCE_HEALTH_FAILED")
    if not item.context_ready:
        reasons.append("SPORT_CONTEXT_NOT_READY")
    if item.model_contributed and not item.model_promotion_passed:
        reasons.append("UNPROMOTED_MODEL_CONTRIBUTION")
    if item.dependence_required and not item.dependence_available:
        reasons.append("DEPENDENCE_EVIDENCE_UNAVAILABLE")
    if item.require_sharp_anchor and not item.sharp_anchor_verified:
        reasons.append("SHARP_ANCHOR_UNVERIFIED")

    eligible = not reasons
    stake = fractional_kelly(item.probability, item.american_odds, fraction=kelly_fraction) if eligible else 0.0
    return RecommendationDecision(
        eligible=eligible,
        reasons=tuple(reasons),
        ev=value,
        kelly_fraction=stake,
    )
