from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sports_ai import SUPPORTED_SPORTS
from sports_ai.betting.prices import implied_prob
from sports_ai.betting.recommend import RecommendationInput, evaluate
from sports_ai.config.settings import Settings
from sports_ai.modeling.blending import blend_log_odds


@dataclass(frozen=True)
class MarketCandidate:
    sport: str
    selection: str
    soft_american_odds: float
    sharp_market_prob: float
    snapshot_age_seconds: float
    market_quality: float
    source_health_passed: bool
    context_ready: bool
    model_prob: float | None = None
    model_promotion_passed: bool = False
    dependence_required: bool = False
    dependence_available: bool = False


class SportsAIEngine:
    """Pure decision core fed by normalized point-in-time market candidates.

    Ingestion stays outside this class during migration. This keeps existing live
    provider routing intact while allowing API handlers and future sport-specific
    adapters to converge on one scoring path.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()

    def evaluate_candidate(self, candidate: MarketCandidate) -> dict[str, Any]:
        sport = candidate.sport.upper()
        if sport not in SUPPORTED_SPORTS:
            raise ValueError(f"unsupported sport: {candidate.sport}")

        model_contributed = candidate.model_prob is not None and candidate.model_promotion_passed
        if model_contributed:
            final_probability = blend_log_odds(
                candidate.sharp_market_prob,
                candidate.model_prob,
                w_market=self.settings.market_weight,
            )
            probability_source = "SHARP_MARKET_PLUS_PROMOTED_MODEL"
        else:
            final_probability = candidate.sharp_market_prob
            probability_source = "SHARP_MARKET_BASELINE"

        soft_probability = implied_prob(candidate.soft_american_odds)
        edge = final_probability - soft_probability
        decision = evaluate(
            RecommendationInput(
                probability=final_probability,
                american_odds=candidate.soft_american_odds,
                edge=edge,
                snapshot_age_seconds=candidate.snapshot_age_seconds,
                market_quality=candidate.market_quality,
                source_health_passed=candidate.source_health_passed,
                context_ready=candidate.context_ready,
                model_contributed=model_contributed,
                model_promotion_passed=candidate.model_promotion_passed,
                dependence_required=candidate.dependence_required,
                dependence_available=candidate.dependence_available,
            ),
            min_edge=self.settings.min_edge,
            min_market_quality=self.settings.min_market_quality,
            max_snapshot_age_seconds=self.settings.max_snapshot_age_seconds,
            kelly_fraction=self.settings.kelly_fraction,
        )
        return {
            "sport": sport,
            "selection": candidate.selection,
            "soft_american_odds": candidate.soft_american_odds,
            "soft_implied_probability": soft_probability,
            "sharp_market_probability": candidate.sharp_market_prob,
            "model_probability": candidate.model_prob,
            "model_promotion_passed": candidate.model_promotion_passed,
            "probability_source": probability_source,
            "final_probability": final_probability,
            "edge": edge,
            "decision": asdict(decision),
        }

    def run_sport(self, sport: str, candidates: list[MarketCandidate]) -> list[dict[str, Any]]:
        normalized = sport.upper()
        if normalized not in SUPPORTED_SPORTS:
            raise ValueError(f"unsupported sport: {sport}")
        if any(candidate.sport.upper() != normalized for candidate in candidates):
            raise ValueError("run_sport received a candidate for a different sport")
        return [self.evaluate_candidate(candidate) for candidate in candidates]

    def run_all(self, candidates_by_sport: dict[str, list[MarketCandidate]]) -> dict[str, list[dict[str, Any]]]:
        return {
            sport: self.run_sport(sport, candidates_by_sport.get(sport, []))
            for sport in SUPPORTED_SPORTS
        }


def run_sport(sport: str, candidates: list[MarketCandidate]) -> list[dict[str, Any]]:
    return SportsAIEngine().run_sport(sport, candidates)


def run_all(candidates_by_sport: dict[str, list[MarketCandidate]]) -> dict[str, list[dict[str, Any]]]:
    return SportsAIEngine().run_all(candidates_by_sport)
