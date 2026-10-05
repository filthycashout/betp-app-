from __future__ import annotations

import numpy as np
import pandas as pd

import governed_train as train
from strict_promote import portable_predict


def _frame(rows: int = 720) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    as_of = pd.date_range("2024-01-01", periods=rows, freq="6h", tz="UTC")
    x1 = rng.normal(size=rows)
    x2 = rng.normal(size=rows)
    x3 = rng.normal(size=rows)
    latent = 0.8 * x1 - 0.35 * x2 + 0.15 * x3
    p = 1.0 / (1.0 + np.exp(-latent))
    y = (rng.random(rows) < p).astype(int)
    return pd.DataFrame({
        "sport": "NFL",
        "event_id": [str(i) for i in range(rows)],
        "event_time": as_of + pd.Timedelta(hours=2),
        "as_of": as_of,
        "home_team": "Home",
        "away_team": "Away",
        "target_home_win": y,
        "market_home_probability": np.clip(0.5 + 0.15 * x1, 0.05, 0.95),
        "label_available_at": as_of + pd.Timedelta(hours=5),
        "feature_a": x1,
        "feature_b": x2,
        "feature_c": x3,
    })


def _evidence():
    return {
        "promotion_pass": False,
        "promotion_evidence": {
            "provenance": {"model_sha256": None},
        },
    }


def test_calibration_method_selection_uses_chronological_validation():
    frame = _frame()
    dev, holdout = train.chronological_holdout(frame, 0.20)
    selector_train, selector_validation = train.chronological_holdout(dev, 0.25)
    method, evidence = train.select_calibration_method(
        selector_train,
        selector_validation,
        ["feature_a", "feature_b", "feature_c"],
        5,
    )
    assert method in {"platt", "isotonic"}
    assert evidence["selected_method"] == method
    assert evidence["validation_rows"] == len(selector_validation)
    assert holdout["as_of"].min() > selector_validation["as_of"].max()
    assert set(evidence["candidate_metrics"]) == {"platt", "isotonic"}


def test_both_calibrator_formats_match_portable_runtime():
    frame = _frame()
    features = ["feature_a", "feature_b", "feature_c"]
    dev, holdout = train.chronological_holdout(frame, 0.20)
    oof_p, oof_y = train.fit_oof(dev, features, 5)
    pipeline = train.make_pipeline()
    pipeline.fit(dev[features], dev["target_home_win"].to_numpy(dtype=int))
    raw = pipeline.predict_proba(holdout[features])[:, 1]

    for method in ("platt", "isotonic"):
        calibrator = train.fit_calibrator(method, oof_p, oof_y)
        expected = train.apply_calibrator(method, calibrator, raw)
        artifact = train.portable_model(
            "NFL",
            pipeline,
            calibrator,
            method,
            features,
            _evidence(),
        )
        actual = portable_predict(artifact, holdout[features].to_numpy(dtype=float))
        assert float(np.max(np.abs(expected - actual))) <= 1e-10
