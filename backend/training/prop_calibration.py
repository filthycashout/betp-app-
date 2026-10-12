from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit

from training.governed_train import apply_calibrator, fit_calibrator, metric_bundle

POLICY = json.loads(Path(__file__).with_name("policy.json").read_text(encoding="utf-8"))
REQUIRED = {
    "sport",
    "market",
    "event_id",
    "event_time",
    "as_of",
    "label_available_at",
    "raw_win_probability",
    "push_probability",
    "target_win",
    "target_push",
}


@dataclass(frozen=True)
class PropPartitions:
    train: pd.DataFrame
    selection_validation: pd.DataFrame
    pre_holdout: pd.DataFrame
    holdout: pd.DataFrame
    selection_cutoff: pd.Timestamp
    holdout_cutoff: pd.Timestamp


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _conditional_raw(frame: pd.DataFrame) -> np.ndarray:
    win = frame["raw_win_probability"].to_numpy(dtype=float)
    push = frame["push_probability"].to_numpy(dtype=float)
    remaining = 1.0 - push
    if np.any(remaining <= 1e-9):
        raise ValueError("push_probability leaves no non-push mass")
    conditional = win / remaining
    if np.any((conditional <= 0.0) | (conditional >= 1.0)):
        raise ValueError("conditional raw win probability must be strictly between 0 and 1")
    return conditional


def _nonpush(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.loc[frame["target_push"] == 0].copy()


def validate_prop_frame(frame: pd.DataFrame, *, sport: str, market: str) -> pd.DataFrame:
    missing = sorted(REQUIRED - set(frame.columns))
    if missing:
        raise ValueError(f"prop calibration frame missing columns: {missing}")
    sport_key = sport.upper().strip()
    market_key = market.strip()
    out = frame.copy()
    out["sport"] = out["sport"].astype(str).str.upper().str.strip()
    out["market"] = out["market"].astype(str).str.strip()
    out = out[(out["sport"] == sport_key) & (out["market"] == market_key)].copy()
    if out.empty:
        raise ValueError("no rows matched requested sport and market")

    for column in ("event_time", "as_of", "label_available_at"):
        out[column] = pd.to_datetime(out[column], utc=True, errors="raise")
    if not bool((out["as_of"] < out["event_time"]).all()):
        raise ValueError("prop chronology violation: require as_of < event_time")
    if not bool((out["label_available_at"] > out["event_time"]).all()):
        raise ValueError("prop labels must become available after event_time")

    for column in ("raw_win_probability", "push_probability"):
        out[column] = pd.to_numeric(out[column], errors="raise")
        if not np.isfinite(out[column].to_numpy(dtype=float)).all():
            raise ValueError(f"non-finite values rejected: {column}")
    if not bool(out["raw_win_probability"].between(0.0, 1.0, inclusive="neither").all()):
        raise ValueError("raw_win_probability must be strictly between 0 and 1")
    if not bool(out["push_probability"].between(0.0, 1.0, inclusive="left").all()):
        raise ValueError("push_probability must be in [0, 1)")
    if bool(((out["raw_win_probability"] + out["push_probability"]) >= 1.0).any()):
        raise ValueError("raw win plus push probability must leave positive loss mass")

    for column in ("target_win", "target_push"):
        out[column] = pd.to_numeric(out[column], errors="raise").astype(int)
        if not set(out[column].unique()).issubset({0, 1}):
            raise ValueError(f"{column} must be binary")
    if bool(((out["target_win"] == 1) & (out["target_push"] == 1)).any()):
        raise ValueError("a settled prop cannot be both a win and a push")

    if out["event_id"].isna().any():
        raise ValueError("event_id cannot be missing")
    out["event_id"] = out["event_id"].astype(str).str.strip()
    if bool((out["event_id"] == "").any()):
        raise ValueError("event_id cannot be empty")

    out = out.sort_values(["as_of", "event_time", "event_id"]).reset_index(drop=True)
    _conditional_raw(_nonpush(out))
    return out


def chronological_partitions(frame: pd.DataFrame) -> PropPartitions:
    if len(frame) < 10:
        raise ValueError("insufficient rows for chronological partitions")
    unique_times = pd.Index(frame["as_of"].sort_values().unique())
    if len(unique_times) < 10:
        raise ValueError("insufficient distinct as_of timestamps")
    selection_index = max(1, int(len(unique_times) * 0.60))
    holdout_index = max(selection_index + 1, int(len(unique_times) * 0.80))
    if holdout_index >= len(unique_times):
        holdout_index = len(unique_times) - 1
    selection_cutoff = pd.Timestamp(unique_times[selection_index])
    holdout_cutoff = pd.Timestamp(unique_times[holdout_index])

    train = frame[(frame["as_of"] < selection_cutoff) & (frame["label_available_at"] < selection_cutoff)].copy()
    selection_validation = frame[(frame["as_of"] >= selection_cutoff) & (frame["as_of"] < holdout_cutoff)].copy()
    pre_holdout = frame[(frame["as_of"] < holdout_cutoff) & (frame["label_available_at"] < holdout_cutoff)].copy()
    holdout = frame[frame["as_of"] >= holdout_cutoff].copy()
    if train.empty or selection_validation.empty or pre_holdout.empty or holdout.empty:
        raise ValueError("chronological prop partitions produced an empty split")
    return PropPartitions(
        train=train.reset_index(drop=True),
        selection_validation=selection_validation.reset_index(drop=True),
        pre_holdout=pre_holdout.reset_index(drop=True),
        holdout=holdout.reset_index(drop=True),
        selection_cutoff=selection_cutoff,
        holdout_cutoff=holdout_cutoff,
    )


def _calibration_payload(method: str, calibrator: Any) -> dict[str, Any]:
    if method == "platt":
        return {
            "type": "platt_logit_logistic",
            "coefficient": float(calibrator.coef_[0][0]),
            "intercept": float(calibrator.intercept_[0]),
        }
    if method == "isotonic":
        return {
            "type": "isotonic",
            "x_thresholds": [float(value) for value in calibrator.X_thresholds_],
            "y_thresholds": [float(value) for value in calibrator.y_thresholds_],
        }
    raise ValueError(f"unsupported calibration method: {method}")


def apply_portable_prop_calibration(
    raw_win_probability: float,
    push_probability: float,
    calibration: dict[str, Any],
) -> dict[str, float]:
    raw_win = float(raw_win_probability)
    push = float(push_probability)
    if not (0.0 < raw_win < 1.0 and 0.0 <= push < 1.0 and raw_win + push < 1.0):
        raise ValueError("invalid raw win/push probabilities")
    nonpush_mass = 1.0 - push
    conditional = raw_win / nonpush_mass
    conditional = min(max(conditional, 1e-6), 1.0 - 1e-6)
    calibration_type = calibration.get("type")
    if calibration_type == "platt_logit_logistic":
        coefficient = float(calibration["coefficient"])
        intercept = float(calibration["intercept"])
        logit = np.log(conditional / (1.0 - conditional))
        calibrated_conditional = 1.0 / (1.0 + np.exp(-(coefficient * logit + intercept)))
    elif calibration_type == "isotonic":
        x = np.asarray(calibration["x_thresholds"], dtype=float)
        y = np.asarray(calibration["y_thresholds"], dtype=float)
        if len(x) < 2 or len(x) != len(y):
            raise ValueError("invalid isotonic thresholds")
        calibrated_conditional = float(np.interp(conditional, x, y, left=y[0], right=y[-1]))
    else:
        raise ValueError("unsupported portable prop calibration")
    calibrated_win = nonpush_mass * float(calibrated_conditional)
    loss = max(0.0, 1.0 - push - calibrated_win)
    return {
        "win_probability": calibrated_win,
        "push_probability": push,
        "loss_probability": loss,
        "conditional_win_probability": float(calibrated_conditional),
    }


def _select_method(train: pd.DataFrame, validation: pd.DataFrame) -> tuple[str, dict[str, Any]]:
    train_nonpush = _nonpush(train)
    valid_nonpush = _nonpush(validation)
    if train_nonpush["target_win"].nunique() != 2 or valid_nonpush["target_win"].nunique() != 2:
        raise ValueError("calibration selection requires both win and loss classes")
    train_p = _conditional_raw(train_nonpush)
    train_y = train_nonpush["target_win"].to_numpy(dtype=int)
    valid_p = _conditional_raw(valid_nonpush)
    valid_y = valid_nonpush["target_win"].to_numpy(dtype=int)
    candidates: dict[str, Any] = {}
    calibrators: dict[str, Any] = {}
    for method in ("platt", "isotonic"):
        calibrator = fit_calibrator(method, train_p, train_y)
        calibrated = apply_calibrator(method, calibrator, valid_p)
        candidates[method] = metric_bundle(valid_y, calibrated)
        calibrators[method] = calibrator
    selected = min(
        candidates,
        key=lambda method: (
            candidates[method]["brier"],
            candidates[method]["ece"],
            candidates[method]["log_loss"],
            method,
        ),
    )
    return selected, {
        "selected_method": selected,
        "selection_metric": "brier_then_ece_then_log_loss",
        "candidate_metrics": candidates,
    }


def _walk_forward_oof(frame: pd.DataFrame, method: str, splits: int = 5) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    nonpush = _nonpush(frame).sort_values(["as_of", "event_time", "event_id"]).reset_index(drop=True)
    times = pd.Index(nonpush["as_of"].sort_values().unique())
    if len(times) <= splits:
        raise ValueError("insufficient timestamps for prop walk-forward calibration")
    predictions: list[float] = []
    labels: list[int] = []
    folds: list[dict[str, Any]] = []
    raw_all = _conditional_raw(nonpush)
    y_all = nonpush["target_win"].to_numpy(dtype=int)
    for train_times, valid_times in TimeSeriesSplit(n_splits=splits).split(times):
        cutoff = pd.Timestamp(times[valid_times[0]])
        train_mask = nonpush["as_of"].isin(times[train_times]) & (nonpush["label_available_at"] < cutoff)
        valid_mask = nonpush["as_of"].isin(times[valid_times])
        train_idx = np.flatnonzero(train_mask.to_numpy())
        valid_idx = np.flatnonzero(valid_mask.to_numpy())
        if not len(train_idx) or not len(valid_idx) or len(np.unique(y_all[train_idx])) < 2:
            continue
        calibrator = fit_calibrator(method, raw_all[train_idx], y_all[train_idx])
        calibrated = apply_calibrator(method, calibrator, raw_all[valid_idx])
        predictions.extend(float(value) for value in calibrated)
        labels.extend(int(value) for value in y_all[valid_idx])
        folds.append(
            {
                "train_rows": len(train_idx),
                "validation_rows": len(valid_idx),
                "latest_training_label_available_at": nonpush.iloc[train_idx]["label_available_at"].max().isoformat(),
                "first_validation_as_of": nonpush.iloc[valid_idx]["as_of"].min().isoformat(),
            }
        )
    return np.asarray(predictions, dtype=float), np.asarray(labels, dtype=int), folds


def train_prop_calibrator(frame: pd.DataFrame, *, sport: str, market: str) -> dict[str, Any]:
    clean = validate_prop_frame(frame, sport=sport, market=market)
    sport_key = sport.upper().strip()
    sample_policy = POLICY["sample_policy"][sport_key]
    nonpush_total = len(_nonpush(clean))
    if len(clean) < int(sample_policy["minimum_total_rows"]):
        raise ValueError(f"insufficient total rows for {sport_key}: {len(clean)}")
    if nonpush_total < int(sample_policy["minimum_total_rows"]):
        raise ValueError(f"insufficient non-push rows for {sport_key}: {nonpush_total}")

    partitions = chronological_partitions(clean)
    holdout_nonpush = _nonpush(partitions.holdout)
    if len(holdout_nonpush) < int(sample_policy["minimum_holdout_rows"]):
        raise ValueError(f"insufficient holdout rows for {sport_key}: {len(holdout_nonpush)}")

    method, selection = _select_method(partitions.train, partitions.selection_validation)
    oof_p, oof_y, folds = _walk_forward_oof(partitions.pre_holdout, method)
    if len(oof_p) < int(sample_policy["minimum_oof_rows"]):
        raise ValueError(f"insufficient OOF rows for {sport_key}: {len(oof_p)}")

    pre_nonpush = _nonpush(partitions.pre_holdout)
    final_calibrator = fit_calibrator(method, _conditional_raw(pre_nonpush), pre_nonpush["target_win"].to_numpy(dtype=int))
    holdout_raw = _conditional_raw(holdout_nonpush)
    holdout_y = holdout_nonpush["target_win"].to_numpy(dtype=int)
    holdout_calibrated = apply_calibrator(method, final_calibrator, holdout_raw)
    raw_metrics = metric_bundle(holdout_y, holdout_raw)
    calibrated_metrics = metric_bundle(holdout_y, holdout_calibrated)
    oof_metrics = metric_bundle(oof_y, oof_p)

    metric_policy = POLICY["metric_policy"]
    brier_improvement = raw_metrics["brier"] - calibrated_metrics["brier"]
    log_loss_regression = calibrated_metrics["log_loss"] - raw_metrics["log_loss"]
    metrics_gate_passed = (
        brier_improvement >= float(metric_policy["minimum_brier_improvement"])
        and log_loss_regression <= float(metric_policy["maximum_log_loss_regression"])
        and calibrated_metrics["ece"] <= float(metric_policy["ece_max"])
    )

    canonical_bytes = clean.to_csv(index=False, date_format="%Y-%m-%dT%H:%M:%S.%f%z").encode("utf-8")
    schema = {
        "schema_version": 1,
        "sport": sport_key,
        "market": market,
        "required_columns": sorted(REQUIRED),
        "target": "target_win conditional on target_push=0",
        "raw_probability": "raw_win_probability / (1 - push_probability)",
        "push_rule": "push mass is preserved outside binary calibrator",
    }
    calibration = _calibration_payload(method, final_calibrator)
    return {
        "artifact_type": "philthy_prop_calibration_candidate_v1",
        "sport": sport_key,
        "market": market,
        "status": "METRICS_GATE_PASSED_UNSIGNED" if metrics_gate_passed else "METRICS_GATE_FAILED",
        "metrics_gate_passed": metrics_gate_passed,
        "promotion_passed": False,
        "runtime_eligible": False,
        "required_next_gate": "ARTIFACT_SIGNING_SCHEMA_REGISTRATION_AND_RUNTIME_PARITY",
        "dataset_sha256": _sha256(canonical_bytes),
        "feature_schema_sha256": _sha256(json.dumps(schema, sort_keys=True, separators=(",", ":")).encode("utf-8")),
        "schema": schema,
        "calibration_method": method,
        "calibration": calibration,
        "sample_evidence": {
            "total_rows": len(clean),
            "nonpush_rows": nonpush_total,
            "train_rows": len(partitions.train),
            "selection_validation_rows": len(partitions.selection_validation),
            "pre_holdout_rows": len(partitions.pre_holdout),
            "holdout_nonpush_rows": len(holdout_nonpush),
            "oof_rows": len(oof_p),
            "minimum_policy": sample_policy,
        },
        "chronology": {
            "selection_cutoff": partitions.selection_cutoff.isoformat(),
            "holdout_cutoff": partitions.holdout_cutoff.isoformat(),
            "oof_folds": folds,
            "passed": True,
        },
        "selection_evidence": selection,
        "oof_metrics": oof_metrics,
        "holdout_raw_metrics": raw_metrics,
        "holdout_calibrated_metrics": calibrated_metrics,
        "metric_deltas": {
            "brier_improvement": brier_improvement,
            "log_loss_regression": log_loss_regression,
        },
        "metric_policy": metric_policy,
        "push_policy": "calibrate conditional win probability on non-push rows; preserve predicted push mass",
    }
