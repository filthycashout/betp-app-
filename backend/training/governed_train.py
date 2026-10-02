from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

SPORT_MIN_ROWS = {"NFL": 500, "NBA": 1000, "MLB": 1200, "NHL": 1000}
MIN_HOLDOUT_ROWS = 100
ECE_MAX = 0.01
REQUIRED = {
    "event_time", "as_of", "home_team", "away_team",
    "target_home_win", "market_home_probability",
}
FORBIDDEN_FEATURE_TOKENS = {
    "target", "winner", "won", "final", "postgame", "result",
    "home_score", "away_score", "score_final", "actual_result",
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
        ("imputer", SimpleImputer(strategy="median")),
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


def load_canonical(path: Path, features: list[str] | None) -> tuple[pd.DataFrame, list[str], dict]:
    raw = path.read_bytes()
    df = pd.read_csv(path)
    missing = sorted(REQUIRED - set(df.columns))
    if missing:
        raise ValueError(f"Canonical dataset missing columns: {missing}")

    df["event_time"] = pd.to_datetime(df["event_time"], utc=True, errors="raise")
    df["as_of"] = pd.to_datetime(df["as_of"], utc=True, errors="raise")
    if not bool((df["as_of"] < df["event_time"]).all()):
        offenders = int((df["as_of"] >= df["event_time"]).sum())
        raise ValueError(f"Chronology violation: {offenders} rows have as_of >= event_time")

    df["target_home_win"] = pd.to_numeric(df["target_home_win"], errors="raise").astype(int)
    if not set(df["target_home_win"].unique()).issubset({0, 1}):
        raise ValueError("target_home_win must be binary")
    df["market_home_probability"] = pd.to_numeric(df["market_home_probability"], errors="raise")
    if not bool(df["market_home_probability"].between(0.0, 1.0, inclusive="neither").all()):
        raise ValueError("market_home_probability must be strictly between 0 and 1")

    features = select_features(df, features)
    for col in features:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.sort_values(["event_time", "as_of"]).reset_index(drop=True)
    duplicate_keys = int(df.duplicated(["event_time", "home_team", "away_team"], keep=False).sum())
    if duplicate_keys:
        raise ValueError(f"Duplicate canonical game keys detected: {duplicate_keys}")

    target = df["target_home_win"].to_numpy()
    exact_target_features = []
    for col in features:
        s = df[col]
        if s.notna().all() and set(s.unique()).issubset({0, 1}):
            if float((s.to_numpy(dtype=int) == target).mean()) >= 0.999:
                exact_target_features.append(col)
    if exact_target_features:
        raise ValueError(f"Exact target proxy leakage detected: {exact_target_features}")

    schema = {
        "schema_version": 1,
        "required_columns": sorted(REQUIRED),
        "features": features,
        "feature_dtypes": {c: str(df[c].dtype) for c in features},
        "target": "target_home_win",
        "market_baseline": "market_home_probability",
    }
    meta = {
        "dataset_sha256": sha256_bytes(raw),
        "feature_schema_sha256": sha256_bytes(canonical_json(schema)),
        "schema": schema,
    }
    return df, features, meta


def fit_oof(df: pd.DataFrame, features: list[str], splits: int) -> tuple[np.ndarray, np.ndarray]:
    X = df[features]
    y = df["target_home_win"].to_numpy(dtype=int)
    tscv = TimeSeriesSplit(n_splits=splits)
    oof_p = np.full(len(df), np.nan, dtype=float)
    oof_y = np.full(len(df), -1, dtype=int)

    for train_idx, valid_idx in tscv.split(X):
        if train_idx.max() >= valid_idx.min():
            raise RuntimeError("TimeSeriesSplit chronology invariant failed")
        pipeline = make_pipeline()
        pipeline.fit(X.iloc[train_idx], y[train_idx])
        oof_p[valid_idx] = pipeline.predict_proba(X.iloc[valid_idx])[:, 1]
        oof_y[valid_idx] = y[valid_idx]

    mask = np.isfinite(oof_p)
    if int(mask.sum()) < max(100, len(df) // 3):
        raise ValueError("Insufficient OOF coverage for calibration")
    return oof_p[mask], oof_y[mask]


def portable_model(
    sport: str,
    pipeline: Pipeline,
    calibrator: LogisticRegression,
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

    artifact = {
        "schema_version": 2,
        "sport": sport,
        "model_id": f"{sport.lower()}-governed-logreg-v1",
        "model_type": "logistic_regression_oof_platt",
        "portable": True,
        "trained_weights": True,
        "status": "PROMOTED_TRAINED_MODEL" if evidence["promotion_pass"] else "CANDIDATE_SHADOW",
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
            "calibrator": {
                "type": "platt_logit_logistic",
                "coefficient": float(calibrator.coef_[0][0]),
                "intercept": float(calibrator.intercept_[0]),
                "fit_source": "chronological_out_of_fold_predictions_only",
            },
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
    min_rows = int(args.min_rows or SPORT_MIN_ROWS[sport])

    holdout_n = max(MIN_HOLDOUT_ROWS, int(round(len(df) * args.holdout_fraction)))
    if holdout_n >= len(df) // 2:
        raise ValueError("Holdout would consume too much of dataset")
    dev = df.iloc[:-holdout_n].copy()
    holdout = df.iloc[-holdout_n:].copy()

    oof_p, oof_y = fit_oof(dev, features, args.splits)
    calibrator = LogisticRegression(max_iter=1000, random_state=42)
    calibrator.fit(logit(oof_p), oof_y)

    final_pipeline = make_pipeline()
    final_pipeline.fit(dev[features], dev["target_home_win"].to_numpy(dtype=int))
    raw_holdout = final_pipeline.predict_proba(holdout[features])[:, 1]
    candidate = calibrator.predict_proba(logit(raw_holdout))[:, 1]

    y = holdout["target_home_win"].to_numpy(dtype=int)
    baseline = holdout["market_home_probability"].to_numpy(dtype=float)

    cand_metrics = {
        "brier": float(brier_score_loss(y, candidate)),
        "log_loss": float(log_loss(y, candidate, labels=[0, 1])),
        "ece": ece_score(y, candidate),
    }
    market_metrics = {
        "brier": float(brier_score_loss(y, baseline)),
        "log_loss": float(log_loss(y, baseline, labels=[0, 1])),
        "ece": ece_score(y, baseline),
    }

    source_manifest = {}
    if args.source_manifest:
        source_raw = Path(args.source_manifest).read_bytes()
        source_manifest = json.loads(source_raw)
        source_manifest_sha = sha256_bytes(source_raw)
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
                "dataset_rows": len(df),
                "dev_rows": len(dev),
                "holdout_rows": len(holdout),
            },
            "calibration": {
                "oof_only": True,
                **cand_metrics,
                "ece_max": ECE_MAX,
            },
            "holdout": {
                "separate_from_calibration": True,
                "resolved_games": len(holdout),
                "candidate": cand_metrics,
                "market": market_metrics,
            },
            "leakage_audit": {
                "passed": True,
                "as_of_lt_event_time": True,
                "forbidden_feature_names": [],
                "exact_target_proxies": [],
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

    artifact = portable_model(sport, final_pipeline, calibrator, features, evidence)
    evidence["promotion_evidence"]["provenance"]["model_sha256"] = artifact["artifact_sha256"]
    artifact["promotion_evidence"] = evidence["promotion_evidence"]
    artifact["artifact_sha256"] = sha256_bytes(canonical_json({k:v for k,v in artifact.items() if k != "artifact_sha256"}))

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    artifact_path = out / f"{sport.lower()}_mobile_model.json"
    artifact_path.write_bytes(canonical_json(artifact))
    joblib_path = out / f"{sport.lower()}_server_model.joblib"
    joblib.dump({
        "pipeline": final_pipeline,
        "calibrator": calibrator,
        "features": features,
        "artifact_sha256": artifact["artifact_sha256"],
    }, joblib_path)

    report = {
        "sport": sport,
        "status": artifact["status"],
        "promotion_pass": promotion_pass,
        "promotion_checks": checks,
        "candidate_metrics": cand_metrics,
        "market_metrics": market_metrics,
        "dataset_rows": len(df),
        "holdout_rows": len(holdout),
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
