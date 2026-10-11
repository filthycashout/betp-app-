from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TRAINING_DIR = Path(__file__).resolve().parents[1] / "training"
if str(TRAINING_DIR) not in sys.path:
    sys.path.insert(0, str(TRAINING_DIR))

import prediction_ledger  # noqa: E402


def _capture_doc(*, baseline: bool, model_identity: bool = False) -> dict:
    game = {
        "sport": "MLB",
        "event_id": "event-1",
        "event_time": "2026-10-12T00:00:00+00:00",
        "date": "2026-10-12",
        "home": "Home",
        "away": "Away",
        "pick": "Home",
        "home_win_probability": 0.55,
        "probability_source": "market_baseline_de_vigged" if baseline else "promoted_trained_model",
        "predictions": {"moneyline": {"pick": "Home", "home_win_probability": 0.55}},
        "market": {"home_ml": -120, "away_ml": 110},
        "model_metadata": {
            "promoted_artifact_loaded": not baseline,
            "promotion_gate": {"passed": not baseline},
        },
        "evidence": {
            "status": "RECORDED",
            "signal_id": "signal-1",
            "record_sha256": "a" * 64,
            "engine_version": "floot-powerhouse-runtime-1.1.0",
            "reason_codes": ["LIVE_PROVIDER_SNAPSHOT", "MARKET_BASELINE", "MODEL_PROMOTION_BLOCKED"]
            if baseline
            else ["LIVE_PROVIDER_SNAPSHOT", "PROMOTED_MODEL"],
        },
    }
    if model_identity:
        game["model_metadata"].update({
            "active_model_id": "mlb-model-v1",
            "promotion_gate": {"passed": True, "artifact_sha256": "b" * 64},
        })
    return {
        "fetched_at": "2026-10-11T17:54:37+00:00",
        "payload": {"games": [game]},
        "source_url": "https://philthyparleys.floot.app/_api/v1/today?days=4",
    }


def _write_capture(tmp_path: Path, doc: dict) -> tuple[Path, Path]:
    root = tmp_path / "evidence"
    capture_dir = tmp_path / "capture"
    capture_dir.mkdir()
    (capture_dir / "powerhouse_raw_20261011T175437Z.json").write_text(
        json.dumps(doc), encoding="utf-8"
    )
    return root, capture_dir


def test_market_baseline_uses_runtime_evidence_identity(tmp_path: Path) -> None:
    root, capture_dir = _write_capture(tmp_path, _capture_doc(baseline=True))

    prediction_ledger.capture(root, capture_dir)
    prediction_ledger.verify(root)

    rows = prediction_ledger._all_prediction_rows(root)
    assert len(rows) == 1
    row = rows[0]
    assert row["model_id"] is None
    assert row["model_artifact_sha256"] is None
    assert row["prediction_evidence_status"] == "RECORDED"
    assert row["prediction_evidence_sha256"] == "a" * 64
    assert row["runtime_engine_version"] == "floot-powerhouse-runtime-1.1.0"
    assert "MARKET_BASELINE" in row["runtime_reason_codes"]

    report = json.loads((root / "prediction_ledger" / "verification.json").read_text())
    assert report["passed"] is True
    assert report["missing_model_identity"] == []


def test_market_baseline_without_evidence_identity_still_fails_closed(tmp_path: Path) -> None:
    doc = _capture_doc(baseline=True)
    doc["payload"]["games"][0]["evidence"] = {}
    root, capture_dir = _write_capture(tmp_path, doc)

    prediction_ledger.capture(root, capture_dir)
    with pytest.raises(SystemExit) as exc:
        prediction_ledger.verify(root)

    assert exc.value.code == 2
    report = json.loads((root / "prediction_ledger" / "verification.json").read_text())
    assert report["passed"] is False
    assert len(report["missing_model_identity"]) == 1


def test_model_driven_prediction_still_requires_model_artifact_identity(tmp_path: Path) -> None:
    root, capture_dir = _write_capture(tmp_path, _capture_doc(baseline=False))

    prediction_ledger.capture(root, capture_dir)
    with pytest.raises(SystemExit) as exc:
        prediction_ledger.verify(root)

    assert exc.value.code == 2


def test_model_driven_prediction_with_model_identity_passes(tmp_path: Path) -> None:
    root, capture_dir = _write_capture(
        tmp_path, _capture_doc(baseline=False, model_identity=True)
    )

    prediction_ledger.capture(root, capture_dir)
    prediction_ledger.verify(root)

    report = json.loads((root / "prediction_ledger" / "verification.json").read_text())
    assert report["passed"] is True
    assert report["missing_model_identity"] == []
