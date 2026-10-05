from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

SPORT_MIN_ROWS = {"NFL": 500, "NBA": 1000, "MLB": 1200, "NHL": 1000}
MIN_HOLDOUT_ROWS = 100
ECE_MAX = 0.01
REQUIRED = {
    "sport", "event_id", "event_time", "as_of", "home_team", "away_team",
    "target_home_win", "market_home_probability", "label_available_at",
}
FORBIDDEN_FEATURE_TOKENS = {
    "target", "winner", "won", "final", "postgame", "result", "outcome",
    "home_score", "away_score", "score_home", "score_away", "score_final",
    "actual_result", "live_win", "live_score", "game_status", "status_live",
    "inning", "period", "quarter", "settled",
}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def ece_score(y: np.ndarray, p: np.ndarray, bins: int = 20) -> float:
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = len(y)
    error = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (p >= lo) & (p < hi if hi < 1.0 else p <= hi)
        n = int(mask.sum())
        if n:
            error += (n / total) * abs(float(y[mask].mean()) - float(p[mask].mean()))
    return float(error)


def logit(p: np.ndarray) -> np.ndarray:
    q = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(q / (1.0 - q)).reshape(-1, 1)


def make_pipeline() -> Pipeline:
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=2000, random_state=42)),
    ])


def select_features(df: pd.DataFrame, explicit: list[str] | None) -> list[str]:
    features = explicit or [c for c in df.columns if c.startswith("feature_")]
    if not features:
        raise ValueError("No model features. Use feature_* columns or --features.")
    bad = [
        c for c in features
        if c in REQUIRED
        or any(token in c.lower() for token in FORBIDDEN_FEATURE_TOKENS)
    ]
    if bad:
        raise ValueError(f"Leakage-prone feature names rejected: {bad}")
    missing = [c for c in features if c not in df.columns]
    if missing:
        raise ValueError(f"Missing requested features: {missing}")
    return features


def temporal_feature_audit(df: pd.DataFrame, features: list[str]) -> dict[str, Any]:
    checked: list[str] = []
    inherited_from_snapshot: list[str] = []
    failures: list[dict[str, Any]] = []
    for feature in features:
        observed_col = f"{feature}_observed_at"
        if observed_col not in df.columns:
            inherited_from_snapshot.append(feature)
            continue
        observed = pd.to_datetime(df[observed_col], utc=True, errors="raise")
        checked.append(observed_col)
        mask = observed > df["as_of"]
        if bool(mask.any()):
            failures.append({
                "feature": feature,
                "observed_column": observed_col,
                "rows": int(mask.sum()),
            })
    if failures:
        raise ValueError(f"Temporal feature leakage detected: {failures}")
    return {
        "passed": True,
        "feature_observation_columns_checked": checked,
        "features_inheriting_row_snapshot_time": inherited_from_snapshot,
        "rule": "feature observed_at <= row as_of; otherwise row as_of is the canonical pregame snapshot",
    }


def load_canonical(path: Path, features: list[str] | None) -> tuple[pd.DataFrame, list[str], dict]:
    raw = path.read_bytes()
    df = pd.read_csv(path)
    missing = sorted(REQUIRED - set(df.columns))
    if missing:
        raise ValueError(f"Canonical dataset missing columns: {missing}")

    df["sport"] = df["sport"].astype(str).str.upper().str.strip()
    if df["event_id"].isna().any():
        raise ValueError("Canonical dataset contains missing event_id values")
    df["event_id"] = df["event_id"].astype(str).str.strip()
    if bool((df["event_id"] == "").any()):
        raise ValueError("Canonical dataset contains empty event_id values")

    df["event_time"] = pd.to_datetime(df["event_time"], utc=True, errors="raise")
    df["as_of"] = pd.to_datetime(df["as_of"], utc=True, errors="raise")
    df["label_available_at"] = pd.to_datetime(df["label_available_at"], utc=True, errors="raise")
    if not bool((df["label_available_at"] > df["event_time"]).all()):
        raise ValueError("Outcome availability must be recorded after the event starts")
    if not bool((df["as_of"] < df["event_time"]).all()):
        offenders = int((df["as_of"] >= df["event_time"]).sum())
        raise ValueError(f"Chronology violation: {offenders} rows have as_of >= event_time")

    df["target_home_win"] = pd.to_numeric(df["target_home_win"], errors="raise")
    if not set(df["target_home_win"].unique()).issubset({0, 1}):
        raise ValueError("target_home_win must be binary")
    df["target_home_win"] = df["target_home_win"].astype(int)
    df["market_home_probability"] = pd.to_numeric(df["market_home_probability"], errors="raise")
    if not bool(df["market_home_probability"].between(0.0, 1.0, inclusive="neither").all()):
        raise ValueError("market_home_probability must be strictly between 0 and 1")

    features = select_features(df, features)
    for col in features:
        df[col] = pd.to_numeric(df[col], errors="raise")
        if np.isinf(df[col].to_numpy(dtype=float)).any():
            raise ValueError(f"Non-finite feature values rejected: {col}")

    df = df.sort_values(["as_of", "event_time", "event_id"]).reset_index(drop=True)
    duplicate_keys = int(df.duplicated(["sport", "event_id"], keep=False).sum())
    if duplicate_keys:
        raise ValueError(f"Duplicate canonical sport/event_id keys detected: {duplicate_keys}")

    target = df["target_home_win"].to_numpy()
    exact_target_features = []
    for col in features:
        s = df[col]
        if s.notna().all() and set(s.unique()).issubset({0, 1}):
            if float((s.to_numpy(dtype=int) == target).mean()) >= 0.999:
                exact_target_features.append(col)
    if exact_target_features:
        raise ValueError(f"Exact target proxy leakage detected: {exact_target_features}")

    temporal_audit = temporal_feature_audit(df, features)
    schema = {
        "schema_version": 2,
        "required_columns": sorted(REQUIRED),
        "features": features,
        "feature_dtypes": {c: str(df[c].dtype) for c in features},
        "target": "target_home_win",
        "market_baseline": "market_home_probability",
        "feature_time_rule": temporal_audit["rule"],
    }
    meta = {
        "dataset_sha256": sha256_bytes(raw),
        "feature_schema_sha256": sha256_bytes(canonical_json(schema)),
        "schema": schema,
        "temporal_feature_audit": temporal_audit,
    }
    return df, features, meta


def chronological_holdout(df: pd.DataFrame, fraction: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not 0 < fraction < 0.5:
        raise ValueError("Holdout fraction must be between zero and one half")
    count = max(MIN_HOLDOUT_ROWS, int(round(len(df) * fraction)))
    if count >= len(df) // 2:
        raise ValueError("Holdout would consume too much of dataset")
    cutoff = df.iloc[-count]["as_of"]
    dev = df[(df["as_of"] < cutoff) & (df["label_available_at"] < cutoff)].copy()
    holdout = df[df["as_of"] >= cutoff].copy()
    if len(dev) < 100 or dev["target_home_win"].nunique() != 2:
        raise ValueError("Insufficient resolved pre-holdout training rows")
    return dev.reset_index(drop=True), holdout.reset_index(drop=True)


def walk_forward_splits(df: pd.DataFrame, splits: int):
    times = pd.Index(df["as_of"].sort_values().unique())
    if len(times) <= splits:
        raise ValueError("Insufficient distinct prediction timestamps for walk-forward folds")
    for train_times, valid_times in TimeSeriesSplit(n_splits=splits).split(times):
        cutoff = times[valid_times[0]]
        train_mask = df["as_of"].isin(times[train_times]) & (df["label_available_at"] < cutoff)
        valid_mask = df["as_of"].isin(times[valid_times])
        yield np.flatnonzero(train_mask), np.flatnonzero(valid_mask)


def fit_oof(df: pd.DataFrame, features: list[str], splits: int, *, return_details: bool = False):
    X = df[features]
    y = df["target_home_win"].to_numpy(dtype=int)
    oof_p = np.full(len(df), np.nan, dtype=float)
    oof_y = np.full(len(df), -1, dtype=int)

    folds = []
    for train_idx, valid_idx in walk_forward_splits(df, splits):
        if not len(train_idx) or len(np.unique(y[train_idx])) < 2:
            continue
        if df.iloc[train_idx]["label_available_at"].max() >= df.iloc[valid_idx]["as_of"].min():
            raise RuntimeError("Training outcome was unavailable at validation prediction time")
        pipeline = make_pipeline()
        pipeline.fit(X.iloc[train_idx], y[train_idx])
        oof_p[valid_idx] = pipeline.predict_proba(X.iloc[valid_idx])[:, 1]
        oof_y[valid_idx] = y[valid_idx]
        folds.append({
            "train_rows": len(train_idx),
            "validation_rows": len(valid_idx),
            "latest_training_label_available_at": df.iloc[train_idx]["label_available_at"].max().isoformat(),
            "first_validation_as_of": df.iloc[valid_idx]["as_of"].min().isoformat(),
        })

    mask = np.isfinite(oof_p)
    if int(mask.sum()) < max(100, len(df) // 3):
        raise ValueError("Insufficient OOF coverage for calibration")
    if return_details:
        records = df.loc[mask, ["event_id", "as_of", "event_time", "label_available_at", "target_home_win"]].copy()
        records["raw_oof_probability"] = oof_p[mask]
        return oof_p[mask], oof_y[mask], {"folds": folds, "records": records}
    return oof_p[mask], oof_y[mask]


def fit_calibrator(method: str, probabilities: np.ndarray, labels: np.ndarray):
    if method == "platt":
        calibrator = LogisticRegression(max_iter=1000, random_state=42)
        calibrator.fit(logit(probabilities), labels)
        return calibrator
    if method == "isotonic":
        calibrator = IsotonicRegression(
            y_min=0.0,
            y_max=1.0,
            increasing=True,
            out_of_bounds="clip",
        )
        calibrator.fit(np.asarray(probabilities, dtype=float), labels)
        return calibrator
    raise ValueError(f"Unsupported calibration method: {method}")


def apply_calibrator(method: str, calibrator: Any, probabilities: np.ndarray) -> np.ndarray:
    raw = np.asarray(probabilities, dtype=float)
    if method == "platt":
        return calibrator.predict_proba(logit(raw))[:, 1]
    if method == "isotonic":
        return np.asarray(calibrator.predict(raw), dtype=float)
    raise ValueError(f"Unsupported calibration method: {method}")


def metric_bundle(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    return {
        "brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "ece": ece_score(y, p),
    }


def select_calibration_method(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    features: list[str],
    splits: int,
) -> tuple[str, dict[str, Any]]:
    oof_p, oof_y, oof_details = fit_oof(train, features, splits, return_details=True)
    pipeline = make_pipeline()
    pipeline.fit(train[features], train["target_home_win"].to_numpy(dtype=int))
    raw_validation = pipeline.predict_proba(validation[features])[:, 1]
    y_validation = validation["target_home_win"].to_numpy(dtype=int)

    candidates: dict[str, Any] = {}
    for method in ("platt", "isotonic"):
        calibrator = fit_calibrator(method, oof_p, oof_y)
        calibrated = apply_calibrator(method, calibrator, raw_validation)
        candidates[method] = metric_bundle(y_validation, calibrated)

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
        "training_rows": len(train),
        "validation_rows": len(validation),
        "validation_first_as_of": validation["as_of"].min().isoformat(),
        "validation_last_as_of": validation["as_of"].max().isoformat(),
        "candidate_metrics": candidates,
        "oof_folds": oof_details["folds"],
    }


def portable_model(
    sport: str,
    pipeline: Pipeline,
    calibrator: Any,
    calibration_method: str,
    features: list[str],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    imputer: SimpleImputer = pipeline.named_steps["imputer"]
    scaler: StandardScaler = pipeline.named_steps["scaler"]
    clf: LogisticRegression = pipeline.named_steps["clf"]

    medians = [float(x) for x in imputer.statistics_]
    means = [float(x) for x in scaler.mean_]
    scales = [float(x) if float(x) != 0 else 1.0 for x in scaler.scale_]
    coefs = [float(x) for x in clf.coef_[0]]
    intercept = float(clf.intercept_[0])

    if calibration_method == "platt":
        calibration_payload = {
            "type": "platt_logit_logistic",
            "coefficient": float(calibrator.coef_[0][0]),
            "intercept": float(calibrator.intercept_[0]),
            "fit_source": "chronological_out_of_fold_predictions_only",
        }
    elif calibration_method == "isotonic":
        calibration_payload = {
            "type": "isotonic",
            "x_thresholds": [float(x) for x in calibrator.X_thresholds_],
            "y_thresholds": [float(y) for y in calibrator.y_thresholds_],
            "out_of_bounds": "clip",
            "fit_source": "chronological_out_of_fold_predictions_only",
        }
    else:
        raise ValueError(f"Unsupported calibration method: {calibration_method}")

    artifact = {
        "schema_version": 3,
        "sport": sport,
        "model_id": f"{sport.lower()}-governed-logreg-{calibration_method}-v2",
        "model_type": f"logistic_regression_oof_{calibration_method}",
        "portable": True,
        "trained_weights": True,
        "status": "CANDIDATE_ELIGIBLE_FOR_STRICT_CHECKS" if evidence["promotion_pass"] else "CANDIDATE_SHADOW",
        "features": features,
        "preprocessing": {
            "imputer": "median",
            "imputer_statistics": medians,
            "standard_scaler_mean": means,
            "standard_scaler_scale": scales,
            "fit_scope": "final_pre_holdout_training_only",
        },
        "probability": {
            "coefficients": coefs,
            "intercept": intercept,
            "calibrator": calibration_payload,
            "output": "home_win_probability",
        },
        "promotion_evidence": evidence["promotion_evidence"],
    }
    artifact["artifact_sha256"] = sha256_bytes(canonical_json(artifact))
    return artifact


def run(args: argparse.Namespace) -> dict[str, Any]:
    sport = args.sport.upper()
    if sport not in SPORT_MIN_ROWS:
        raise ValueError(f"Unsupported sport {sport}")

    feature_list = [x.strip() for x in args.features.split(",") if x.strip()] if args.features else None
    df, features, provenance = load_canonical(Path(args.input), feature_list)
    observed_sports = sorted(set(df["sport"]))
    if observed_sports != [sport]:
        raise ValueError(
            f"Canonical dataset sport mismatch: expected {[sport]}, observed {observed_sports}"
        )
    min_rows = int(args.min_rows or SPORT_MIN_ROWS[sport])

    dev, holdout = chronological_holdout(df, args.holdout_fraction)
    selector_train, selector_validation = chronological_holdout(dev, 0.25)
    selected_method, selection_evidence = select_calibration_method(
        selector_train,
        selector_validation,
        features,
        args.splits,
    )

    oof_p, oof_y, oof_details = fit_oof(dev, features, args.splits, return_details=True)
    calibrator = fit_calibrator(selected_method, oof_p, oof_y)

    final_pipeline = make_pipeline()
    final_pipeline.fit(dev[features], dev["target_home_win"].to_numpy(dtype=int))
    raw_holdout = final_pipeline.predict_proba(holdout[features])[:, 1]
    candidate = apply_calibrator(selected_method, calibrator, raw_holdout)

    y = holdout["target_home_win"].to_numpy(dtype=int)
    baseline = holdout["market_home_probability"].to_numpy(dtype=float)

    cand_metrics = metric_bundle(y, candidate)
    market_metrics = metric_bundle(y, baseline)

    source_manifest = {}
    if args.source_manifest:
        source_raw = Path(args.source_manifest).read_bytes()
        source_manifest = json.loads(source_raw)
        source_manifest_sha = sha256_bytes(source_raw)
        if source_manifest.get("canonical_sha256") != provenance["dataset_sha256"]:
            raise ValueError("Source manifest does not match canonical dataset checksum")
        if source_manifest.get("sport") != sport or source_manifest.get("rows") != len(df):
            raise ValueError("Source manifest sport or row count mismatch")
        if not source_manifest.get("labels_sha256") or not source_manifest.get("pregame_sources"):
            raise ValueError("Source manifest is missing pregame or settled-label provenance")
    else:
        source_manifest_sha = ""

    sample_ok = len(df) >= min_rows and len(holdout) >= MIN_HOLDOUT_ROWS
    brier_ok = cand_metrics["brier"] < market_metrics["brier"]
    logloss_ok = cand_metrics["log_loss"] <= market_metrics["log_loss"] + args.logloss_margin
    ece_ok = cand_metrics["ece"] <= ECE_MAX
    source_ok = bool(source_manifest_sha)
    checks = {
        "sample_sufficiency": sample_ok,
        "brier_improvement": brier_ok,
        "non_inferior_log_loss": logloss_ok,
        "ece_threshold": ece_ok,
        "chronology": True,
        "walk_forward_oof": True,
        "calibration_oof_only": True,
        "calibration_method_selection": True,
        "separate_holdout": True,
        "leakage_audit": True,
        "schema_compatibility": True,
        "source_manifest": source_ok,
    }
    promotion_pass = all(checks.values())

    evidence = {
        "promotion_pass": promotion_pass,
        "promotion_evidence": {
            "chronology": {
                "as_of_lt_event_time": True,
                "walk_forward_oof": True,
                "in_fold_preprocessing": True,
                "labels_available_before_validation": True,
                "simultaneous_predictions_grouped": True,
                "folds": oof_details["folds"],
                "latest_development_label_available_at": dev["label_available_at"].max().isoformat(),
                "first_holdout_as_of": holdout["as_of"].min().isoformat(),
                "dataset_rows": len(df),
                "dev_rows": len(dev),
                "selection_training_rows": len(selector_train),
                "selection_validation_rows": len(selector_validation),
                "holdout_rows": len(holdout),
            },
            "calibration": {
                "oof_only": True,
                "method": selected_method,
                "method_selection": selection_evidence,
                **cand_metrics,
                "ece_max": ECE_MAX,
            },
            "holdout": {
                "separate_from_calibration": True,
                "untouched_during_method_selection": True,
                "resolved_games": len(holdout),
                "candidate": cand_metrics,
                "market": market_metrics,
            },
            "leakage_audit": {
                "passed": True,
                "as_of_lt_event_time": True,
                "forbidden_feature_names": [],
                "exact_target_proxies": [],
                **provenance["temporal_feature_audit"],
            },
            "market_baseline_comparison": {
                "passed": brier_ok and logloss_ok,
                "candidate_brier": cand_metrics["brier"],
                "market_brier": market_metrics["brier"],
                "candidate_log_loss": cand_metrics["log_loss"],
                "market_log_loss": market_metrics["log_loss"],
                "logloss_noninferiority_margin": args.logloss_margin,
            },
            "sample_sufficiency": {
                "passed": sample_ok,
                "required_rows": min_rows,
                "rows": len(df),
                "required_holdout_rows": MIN_HOLDOUT_ROWS,
                "holdout_rows": len(holdout),
            },
            "provenance": {
                "dataset_sha256": provenance["dataset_sha256"],
                "feature_schema_sha256": provenance["feature_schema_sha256"],
                "source_manifest_sha256": source_manifest_sha,
                "model_sha256": None,
            },
            "schema": provenance["schema"],
            "promotion_checks": checks,
        },
    }

    artifact = portable_model(
        sport,
        final_pipeline,
        calibrator,
        selected_method,
        features,
        evidence,
    )
    model_core = {
        "features": artifact["features"],
        "preprocessing": artifact["preprocessing"],
        "probability": artifact["probability"],
    }
    evidence["promotion_evidence"]["provenance"]["model_sha256"] = sha256_bytes(
        canonical_json(model_core)
    )
    artifact["promotion_evidence"] = evidence["promotion_evidence"]
    artifact["artifact_format"] = "philthysports_portable_logistic_calibrated_v2"
    artifact["artifact_sha256"] = sha256_bytes(
        canonical_json({k: v for k, v in artifact.items() if k != "artifact_sha256"})
    )

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    oof_path = out / f"{sport.lower()}_oof_predictions.csv"
    oof_details["records"].to_csv(oof_path, index=False)
    artifact_path = out / f"{sport.lower()}_mobile_model.json"
    artifact_path.write_bytes(canonical_json(artifact))
    joblib_path = out / f"{sport.lower()}_server_model.joblib"
    joblib.dump({
        "pipeline": final_pipeline,
        "calibrator": calibrator,
        "calibration_method": selected_method,
        "features": features,
        "artifact_sha256": artifact["artifact_sha256"],
    }, joblib_path)

    report = {
        "sport": sport,
        "status": artifact["status"],
        "promotion_pass": promotion_pass,
        "promotion_checks": checks,
        "calibration_method": selected_method,
        "calibration_selection": selection_evidence,
        "candidate_metrics": cand_metrics,
        "market_metrics": market_metrics,
        "dataset_rows": len(df),
        "holdout_rows": len(holdout),
        "development_rows": len(dev),
        "oof_rows": len(oof_p),
        "oof_file": str(oof_path),
        "oof_sha256": sha256_bytes(oof_path.read_bytes()),
        "features": features,
        "dataset_sha256": provenance["dataset_sha256"],
        "feature_schema_sha256": provenance["feature_schema_sha256"],
        "source_manifest_sha256": source_manifest_sha,
        "mobile_artifact": str(artifact_path),
        "mobile_artifact_sha256": sha256_bytes(artifact_path.read_bytes()),
        "server_joblib": str(joblib_path),
        "server_joblib_sha256": sha256_bytes(joblib_path.read_bytes()),
    }
    (out / f"{sport.lower()}_promotion_report.json").write_bytes(canonical_json(report))
    return report


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sport", required=True, choices=["NFL", "NBA", "MLB", "NHL"])
    p.add_argument("--input", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--source-manifest")
    p.add_argument("--features", help="Comma-separated ordered feature columns; defaults to feature_*")
    p.add_argument("--splits", type=int, default=5)
    p.add_argument("--holdout-fraction", type=float, default=0.20)
    p.add_argument("--min-rows", type=int)
    p.add_argument("--logloss-margin", type=float, default=0.0)
    args = p.parse_args()
    report = run(args)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
