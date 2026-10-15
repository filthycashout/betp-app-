from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from training.prop_calibration import (
    apply_portable_prop_calibration,
    train_prop_calibrator,
    validate_prop_frame,
)


def synthetic_nfl_frame(rows: int = 1300) -> pd.DataFrame:
    start = datetime(2023, 1, 1, 12, tzinfo=timezone.utc)
    records = []
    for i in range(rows):
        as_of = start + timedelta(days=i)
        event_time = as_of + timedelta(hours=6)
        # Repeating local patterns make the raw model deliberately overconfident:
        # low raw conditional p=.2 settles at 40%; high p=.8 settles at 60%.
        high = (i // 10) % 2 == 1
        raw_conditional = 0.8 if high else 0.2
        position = i % 10
        target_win = int(position < (6 if high else 4))
        records.append(
            {
                "sport": "NFL",
                "market": "player_receptions",
                "event_id": f"event-{i}",
                "event_time": event_time,
                "as_of": as_of,
                "label_available_at": event_time + timedelta(hours=4),
                "raw_win_probability": raw_conditional,
                "push_probability": 0.0,
                "target_win": target_win,
                "target_push": 0,
            }
        )
    return pd.DataFrame(records)


def test_validate_prop_frame_rejects_prediction_after_event() -> None:
    frame = synthetic_nfl_frame(20)
    frame.loc[0, "as_of"] = frame.loc[0, "event_time"]
    with pytest.raises(ValueError, match="as_of < event_time"):
        validate_prop_frame(frame, sport="NFL", market="player_receptions")


def test_portable_calibration_preserves_push_mass() -> None:
    result = apply_portable_prop_calibration(
        raw_win_probability=0.54,
        push_probability=0.10,
        calibration={
            "type": "platt_logit_logistic",
            "coefficient": 1.0,
            "intercept": 0.0,
        },
    )
    assert result["push_probability"] == pytest.approx(0.10)
    assert result["win_probability"] == pytest.approx(0.54)
    assert result["loss_probability"] == pytest.approx(0.36)
    assert sum((result["win_probability"], result["push_probability"], result["loss_probability"])) == pytest.approx(1.0)


def test_prop_calibration_reuses_strict_promotion_metrics_but_remains_unsigned() -> None:
    result = train_prop_calibrator(
        synthetic_nfl_frame(),
        sport="NFL",
        market="player_receptions",
    )
    assert result["sample_evidence"]["total_rows"] == 1300
    assert result["sample_evidence"]["nonpush_rows"] == 1300
    assert result["sample_evidence"]["oof_rows"] >= 600
    assert result["sample_evidence"]["holdout_nonpush_rows"] >= 240
    assert result["metrics_gate_passed"] is True
    assert result["holdout_calibrated_metrics"]["brier"] < result["holdout_raw_metrics"]["brier"]
    assert result["holdout_calibrated_metrics"]["log_loss"] <= result["holdout_raw_metrics"]["log_loss"]
    assert result["holdout_calibrated_metrics"]["ece"] <= 0.01
    assert result["promotion_passed"] is False
    assert result["runtime_eligible"] is False
    assert result["required_next_gate"] == "ARTIFACT_SIGNING_SCHEMA_REGISTRATION_AND_RUNTIME_PARITY"
    assert result["status"] == "METRICS_GATE_PASSED_UNSIGNED"


def test_prop_calibration_rejects_insufficient_sample() -> None:
    with pytest.raises(ValueError, match="insufficient total rows"):
        train_prop_calibrator(
            synthetic_nfl_frame(1199),
            sport="NFL",
            market="player_receptions",
        )
