from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from training.sports_omni_contract import (
    CanonicalAdmissionError,
    admit_csv,
    model_feature_columns,
    to_trainer_contract,
)


def frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "sport": "NFL",
                "event_id": "evt-1",
                "event_time": "2026-09-01T20:00:00Z",
                "snapshot_time": "2026-09-01T18:00:00Z",
                "settled_time": "2026-09-02T01:00:00Z",
                "target": 1,
                "market_prob": 0.57,
                "consensus_de_vig_home_probability": 0.56,
                "home_spread": -2.5,
                "consensus_total": 44.5,
                "home_team": "Home",
                "away_team": "Away",
                "feature_rest_days": 6,
                "feature_rest_days_observed_at": "2026-09-01T17:55:00Z",
            },
            {
                "sport": "NFL",
                "event_id": "evt-2",
                "event_time": "2026-09-08T20:00:00Z",
                "snapshot_time": "2026-09-08T18:00:00Z",
                "settled_time": "2026-09-09T01:00:00Z",
                "target": 0,
                "market_prob": 0.48,
                "consensus_de_vig_home_probability": 0.49,
                "home_spread": 1.0,
                "consensus_total": 46.0,
                "home_team": "Other Home",
                "away_team": "Other Away",
                "feature_rest_days": 7,
                "feature_rest_days_observed_at": "2026-09-08T17:50:00Z",
            },
        ]
    )


def test_drive_schema_maps_to_governed_trainer_without_timestamps_becoming_features():
    result = to_trainer_contract(frame())
    assert "as_of" in result
    assert "label_available_at" in result
    assert "target_home_win" in result
    assert "market_home_probability" in result
    assert model_feature_columns(result) == ["feature_rest_days"]
    assert "feature_rest_days_observed_at" in result


def test_feature_observed_after_snapshot_is_rejected():
    bad = frame()
    bad.loc[0, "feature_rest_days_observed_at"] = "2026-09-01T18:01:00Z"
    with pytest.raises(CanonicalAdmissionError, match="after snapshot"):
        to_trainer_contract(bad)


def test_postgame_feature_name_is_rejected():
    bad = frame()
    bad["feature_final_score"] = [21, 17]
    with pytest.raises(CanonicalAdmissionError, match="Leakage-prone|leakage-prone"):
        to_trainer_contract(bad)


def test_incoming_manifest_cannot_self_promote(tmp_path: Path):
    csv_path = tmp_path / "incoming.csv"
    frame().to_csv(csv_path, index=False)
    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"source": "test", "sha256": digest, "promotion_eligible": True}))
    with pytest.raises(CanonicalAdmissionError, match="self-declare"):
        admit_csv(csv_path, manifest, tmp_path / "out.csv", tmp_path / "out.json")


def test_admission_emits_candidate_only_manifest(tmp_path: Path):
    csv_path = tmp_path / "incoming.csv"
    frame().to_csv(csv_path, index=False)
    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"source": "verified-test-fixture", "sha256": digest, "promotion_eligible": False}))
    result = admit_csv(csv_path, manifest, tmp_path / "out.csv", tmp_path / "out.json")
    assert result["rows"] == 2
    assert result["features"] == ["feature_rest_days"]
    assert result["authority"]["promotion_eligible"] is False
    assert result["authority"]["candidate_only"] is True
