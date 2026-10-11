from __future__ import annotations

import math
import unittest
from datetime import datetime, timedelta, timezone

from sports_ai.betting.clv import price_clv, probability_clv
from sports_ai.betting.devig import no_vig_two_way
from sports_ai.betting.ev import expected_value
from sports_ai.betting.kelly import fractional_kelly
from sports_ai.betting.prices import american_to_decimal, implied_prob
from sports_ai.config.settings import Settings
from sports_ai.core.snapshots import SnapshotMeta, assert_snapshot_usable
from sports_ai.modeling.blending import blend_log_odds
from sports_ai.orchestrator import MarketCandidate, SportsAIEngine


class SportsAICoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            min_edge=0.03,
            min_market_quality=0.75,
            max_snapshot_age_seconds=900,
            market_weight=0.70,
            kelly_fraction=0.25,
        )
        self.settings.validate()
        self.engine = SportsAIEngine(self.settings)

    def test_price_math(self) -> None:
        self.assertEqual(american_to_decimal(100), 2.0)
        self.assertTrue(math.isclose(american_to_decimal(-110), 1.909090909, rel_tol=1e-8))
        self.assertEqual(implied_prob(100), 0.5)

    def test_two_way_devig_sums_to_one(self) -> None:
        a, b = no_vig_two_way(-110, -110)
        self.assertTrue(math.isclose(a + b, 1.0, rel_tol=1e-12))
        self.assertTrue(math.isclose(a, 0.5, rel_tol=1e-12))

    def test_ev_kelly_and_clv(self) -> None:
        self.assertGreater(expected_value(0.55, 100), 0.0)
        self.assertGreater(fractional_kelly(0.55, 100), 0.0)
        self.assertGreater(price_clv(120, 100), 0.0)
        self.assertGreater(probability_clv(0.50, 0.54), 0.0)

    def test_blend_is_between_inputs(self) -> None:
        blended = blend_log_odds(0.55, 0.65, w_market=0.70)
        self.assertGreater(blended, 0.55)
        self.assertLess(blended, 0.65)

    def test_point_in_time_snapshot_gate(self) -> None:
        event = datetime(2026, 10, 12, 2, tzinfo=timezone.utc)
        prediction = event - timedelta(minutes=20)
        observed = prediction - timedelta(minutes=3)
        assert_snapshot_usable(
            SnapshotMeta(observed, prediction, event, "fixture-source"),
            max_age_seconds=900,
        )
        with self.assertRaises(ValueError):
            assert_snapshot_usable(
                SnapshotMeta(event, prediction, event, "fixture-source"),
                max_age_seconds=900,
            )

    def test_market_baseline_remains_available_when_model_is_not_promoted(self) -> None:
        result = self.engine.evaluate_candidate(
            MarketCandidate(
                sport="MLB",
                selection="fixture-selection",
                soft_american_odds=100,
                sharp_market_prob=0.55,
                model_prob=0.70,
                model_promotion_passed=False,
                snapshot_age_seconds=60,
                market_quality=0.90,
                source_health_passed=True,
                context_ready=True,
            )
        )
        self.assertEqual(result["probability_source"], "SHARP_MARKET_BASELINE")
        self.assertTrue(math.isclose(result["final_probability"], 0.55, rel_tol=1e-12))
        self.assertTrue(result["decision"]["eligible"])

    def test_promoted_model_can_contribute(self) -> None:
        result = self.engine.evaluate_candidate(
            MarketCandidate(
                sport="NBA",
                selection="fixture-selection",
                soft_american_odds=100,
                sharp_market_prob=0.54,
                model_prob=0.64,
                model_promotion_passed=True,
                snapshot_age_seconds=60,
                market_quality=0.90,
                source_health_passed=True,
                context_ready=True,
            )
        )
        self.assertEqual(result["probability_source"], "SHARP_MARKET_PLUS_PROMOTED_MODEL")
        self.assertGreater(result["final_probability"], 0.54)

    def test_stale_market_and_missing_dependence_fail_closed(self) -> None:
        stale = self.engine.evaluate_candidate(
            MarketCandidate(
                sport="NFL",
                selection="fixture-selection",
                soft_american_odds=100,
                sharp_market_prob=0.60,
                snapshot_age_seconds=901,
                market_quality=0.90,
                source_health_passed=True,
                context_ready=True,
            )
        )
        self.assertFalse(stale["decision"]["eligible"])
        self.assertIn("STALE_SNAPSHOT", stale["decision"]["reasons"])

        correlated = self.engine.evaluate_candidate(
            MarketCandidate(
                sport="NHL",
                selection="fixture-selection",
                soft_american_odds=100,
                sharp_market_prob=0.60,
                snapshot_age_seconds=60,
                market_quality=0.90,
                source_health_passed=True,
                context_ready=True,
                dependence_required=True,
                dependence_available=False,
            )
        )
        self.assertFalse(correlated["decision"]["eligible"])
        self.assertIn("DEPENDENCE_EVIDENCE_UNAVAILABLE", correlated["decision"]["reasons"])


if __name__ == "__main__":
    unittest.main()
