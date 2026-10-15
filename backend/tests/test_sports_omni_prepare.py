from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from training.sports_omni_prepare import prepare


def test_prepare_builds_features_adapts_contract_and_does_not_promote(tmp_path: Path):
    rows = [
        {
            "sport": "NHL",
            "event_id": "n1",
            "event_time": "2026-01-01T20:00:00Z",
            "snapshot_time": "2026-01-01T18:00:00Z",
            "settled_time": "2026-01-01T23:00:00Z",
            "target": 1,
            "market_prob": 0.52,
            "consensus_de_vig_home_probability": 0.51,
            "home_spread": -1.5,
            "consensus_total": 6.0,
            "home_team": "A",
            "away_team": "B",
            "home_score": 4,
            "away_score": 2,
        },
        {
            "sport": "NHL",
            "event_id": "n2",
            "event_time": "2026-01-03T20:00:00Z",
            "snapshot_time": "2026-01-03T18:00:00Z",
            "settled_time": "2026-01-03T23:00:00Z",
            "target": 0,
            "market_prob": 0.49,
            "consensus_de_vig_home_probability": 0.48,
            "home_spread": 1.5,
            "consensus_total": 6.5,
            "home_team": "C",
            "away_team": "A",
            "home_score": 2,
            "away_score": 3,
        },
    ]
    source_csv = tmp_path / "nhl.csv"
    pd.DataFrame(rows).to_csv(source_csv, index=False)
    manifest = tmp_path / "nhl_source_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "source": "test canonical fixture",
                "sha256": hashlib.sha256(source_csv.read_bytes()).hexdigest(),
                "promotion_eligible": False,
            }
        )
    )
    result = prepare(source_csv, manifest, tmp_path / "prepared")
    assert result["status"] == "PREPARED_CANDIDATE_ONLY"
    assert result["promotion_executed"] is False
    assert Path(result["trainer_csv"]).exists()
    trainer = pd.read_csv(result["trainer_csv"])
    assert "feature_market_home_prob" in trainer
    assert "feature_home_games_prior" in trainer
    assert "target_home_win" in trainer
    assert "snapshot_time" not in trainer

    command = result["next_governed_training_command"]
    assert "governed_train.py" in command
    assert "--features " in command
    assert result["features"]
    assert all(name.startswith("feature_") for name in result["features"])
    assert all(not name.endswith("_observed_at") for name in result["features"])
    for name in result["features"]:
        assert name in trainer.columns
        assert f"{name}_observed_at" in trainer.columns
    feature_arg = command.split("--features ", 1)[1].split(" --output-dir", 1)[0]
    assert feature_arg.split(",") == result["features"]
    assert "_observed_at" not in feature_arg
