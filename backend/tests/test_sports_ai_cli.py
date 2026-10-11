from __future__ import annotations

import unittest
from unittest.mock import patch

import main as sports_main
from sports_ai.config.settings import Settings


FIXTURE = {
    "selection": "fixture-selection",
    "soft_american_odds": 100,
    "market_anchor_prob": 0.55,
    "snapshot_age_seconds": 60,
    "market_quality": 0.90,
    "source_health_passed": True,
    "context_ready": True,
}


class SportsAICliTests(unittest.TestCase):
    def test_run_sport_uses_one_entrypoint(self) -> None:
        settings = Settings(
            min_edge=0.03,
            min_market_quality=0.75,
            max_snapshot_age_seconds=900,
            market_weight=0.70,
            kelly_fraction=0.25,
        )
        with patch("main.SportsAIEngine") as engine_cls:
            engine = engine_cls.return_value
            engine.run_sport.return_value = [{"sport": "MLB", "decision": {"eligible": True}}]
            result = sports_main.run_sport("MLB", [FIXTURE])
            self.assertEqual(result[0]["sport"], "MLB")
            engine_cls.assert_called_once()
            args = engine.run_sport.call_args.args
            self.assertEqual(args[0], "MLB")
            self.assertEqual(args[1][0].sport, "MLB")
            self.assertEqual(settings.min_edge, 0.03)

    def test_run_all_builds_all_four_sports(self) -> None:
        with patch("main.SportsAIEngine") as engine_cls:
            engine = engine_cls.return_value
            engine.run_all.return_value = {sport: [] for sport in ("MLB", "NHL", "NBA", "NFL")}
            result = sports_main.run_all({"NFL": [FIXTURE]})
            self.assertEqual(set(result), {"MLB", "NHL", "NBA", "NFL"})
            payload = engine.run_all.call_args.args[0]
            self.assertEqual(len(payload["NFL"]), 1)
            self.assertEqual(payload["NFL"][0].sport, "NFL")
            self.assertEqual(payload["MLB"], [])


if __name__ == "__main__":
    unittest.main()
