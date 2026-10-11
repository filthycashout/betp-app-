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
    market_anchor_prob: float
    snapshot_age_seconds: float
    market_quality: float
    source_health_passed: bool
    context_ready: bool
    event_id: str = ""
    market: str = "moneyline"
    line: float | None = None
    model_prob: float | None = None
    model_promotion_passed: bool = False
    model_includes_market: bool = False
    market_anchor_kind: str = "DEVIG_CONSENSUS"
    sharp_anchor_verified: bool = False
    require_sharp_anchor: bool = False
    dependence_required: bool = False
    dependence_available: bool = False


class SportsAIEngine:
    """Pure decision core fed by normalized point-in-time market candidates.

    A promoted model that already consumed market probability must set
    `model_includes_market=True`; its calibrated probability is then used
    directly rather than blended with the same market a second time.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()

    def evaluate_candidate(self, candidate: MarketCandidate) -> dict[str, Any]:
        sport = candidate.sport.upper()
        if sport not in SUPPORTED_SPORTS:
            raise ValueError(f"unsupported sport: {candidate.sport}")
        if not candidate.market_anchor_kind.strip():
            raise ValueError("market_anchor_kind is required")

        model_contributed = candidate.model_prob is not None and candidate.model_promotion_passed
        if model_contributed and candidate.model_includes_market:
            final_probability = float(candidate.model_prob)
            probability_source = "PROMOTED_MARKET_CONDITIONED_MODEL"
            probability_method = "promoted_calibrated_model_already_conditions_on_market"
        elif model_contributed:
            final_probability = blend_log_odds(
                candidate.market_anchor_prob,
                float(candidate.model_prob),
                w_market=self.settings.market_weight,
            )
            probability_source = (
                "SHARP_ANCHOR_PLUS_PROMOTED_MODEL"
                if candidate.sharp_anchor_verified
                else "MARKET_ANCHOR_PLUS_PROMOTED_MODEL"
            )
            probability_method = "log_odds_market_model_blend"
        else:
            final_probability = candidate.market_anchor_prob
            probability_source = (
                "SHARP_MARKET_BASELINE"
                if candidate.sharp_anchor_verified
                else "MARKET_BASELINE"
            )
            probability_method = "market_anchor_only"

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
                require_sharp_anchor=candidate.require_sharp_anchor,
                sharp_anchor_verified=candidate.sharp_anchor_verified,
            ),
            min_edge=self.settings.min_edge,
            min_market_quality=self.settings.min_market_quality,
            max_snapshot_age_seconds=self.settings.max_snapshot_age_seconds,
            kelly_fraction=self.settings.kelly_fraction,
        )
        return {
            "sport": sport,
            "event_id": candidate.event_id,
            "market": candidate.market,
            "line": candidate.line,
            "selection": candidate.selection,
            "soft_american_odds": candidate.soft_american_odds,
            "soft_implied_probability": soft_probability,
            "market_anchor_probability": candidate.market_anchor_prob,
            "market_anchor_kind": candidate.market_anchor_kind,
            "sharp_anchor_verified": candidate.sharp_anchor_verified,
            "model_probability": candidate.model_prob,
            "model_promotion_passed": candidate.model_promotion_passed,
            "model_includes_market": candidate.model_includes_market,
            "probability_source": probability_source,
            "probability_method": probability_method,
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
