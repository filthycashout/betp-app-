from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sklearn.calibration import calibration_curve
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parent
POLICY_PATH = ROOT / "policy.json"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _load_policy() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text())


def _read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if suffix in {".csv", ".txt"}:
        return pd.read_csv(path)
    if suffix in {".jsonl", ".ndjson"}:
        return pd.read_json(path, lines=True)
    if suffix == ".json":
        return pd.read_json(path)
    raise ValueError(f"Unsupported canonical training file: {path.name}")


def _ece(y_true: np.ndarray, prob: np.ndarray, bins: int = 15) -> float:
    y = np.asarray(y_true, dtype=float)
    p = np.clip(np.asarray(prob, dtype=float), 1e-9, 1 - 1e-9)
    edges = np.linspace(0.0, 1.0, bins + 1)
    result = 0.0
    for left, right in zip(edges[:-1], edges[1:]):
        if right == 1.0:
            mask = (p >= left) & (p <= right)
        else:
            mask = (p >= left) & (p < right)
        n = int(mask.sum())
        if not n:
            continue
        result += (n / len(p)) * abs(float(y[mask].mean()) - float(p[mask].mean()))
    return float(result)


def _metrics(y_true: np.ndarray, prob: np.ndarray) -> dict[str, float]:
    p = np.clip(np.asarray(prob, dtype=float), 1e-9, 1 - 1e-9)
    y = np.asarray(y_true, dtype=int)
    return {
        "brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "ece": _ece(y, p),
        "accuracy": float(np.mean((p >= 0.5).astype(int) == y)),
    }


def _build_pipeline() -> Pipeline:
    return Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            (
                "model",
                LogisticRegression(
                    solver="lbfgs",
                    max_iter=4000,
                    random_state=42,
                ),
            ),
        ]
    )


@dataclass
class IsotonicPortable:
    x: list[float]
    y: list[float]

    def predict(self, values: np.ndarray) -> np.ndarray:
        p = np.asarray(values, dtype=float)
        if not self.x:
            return p
        return np.interp(p, np.asarray(self.x), np.asarray(self.y), left=self.y[0], right=self.y[-1])


def _fit_isotonic(raw_prob: np.ndarray, outcomes: np.ndarray) -> IsotonicPortable:
    from sklearn.isotonic import IsotonicRegression

    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(raw_prob, outcomes)
    return IsotonicPortable(
        x=[float(v) for v in calibrator.X_thresholds_],
        y=[float(v) for v in calibrator.y_thresholds_],
    )


def _validate_and_sort(
    frame: pd.DataFrame,
    sport: str,
    policy: dict[str, Any],
) -> tuple[pd.DataFrame, list[str]]:
    runtime = policy["runtime_schema"]
    required = list(runtime["required_columns"])
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"Canonical dataset missing required columns: {missing}")

    df = frame.copy()
    df["sport"] = df["sport"].astype(str).str.upper()
    df = df[df["sport"] == sport].copy()
    if df.empty:
        raise ValueError(f"No rows found for sport={sport}")

    df["event_time"] = pd.to_datetime(df["event_time"], utc=True, errors="raise")
    df["as_of"] = pd.to_datetime(df["as_of"], utc=True, errors="raise")
    if not bool((df["as_of"] < df["event_time"]).all()):
        bad = int((df["as_of"] >= df["event_time"]).sum())
        raise ValueError(f"Leakage gate failed: {bad} rows have as_of >= event_time")

    if df["event_id"].isna().any() or df["event_id"].astype(str).str.len().eq(0).any():
        raise ValueError("event_id must be non-empty")
    if df["event_id"].astype(str).duplicated().any():
        raise ValueError("event_id must be unique within a canonical sport dataset")

    target = pd.to_numeric(df["target_home_win"], errors="raise")
    if not target.isin([0, 1]).all():
        raise ValueError("target_home_win must contain only 0/1")
    df["target_home_win"] = target.astype(int)

    for column in ("market_home_probability", *runtime["features"]):
        df[column] = pd.to_numeric(df[column], errors="coerce")

    if not df["market_home_probability"].between(0.0, 1.0, inclusive="both").all():
        raise ValueError("market_home_probability must be populated and within [0,1] for baseline comparison")

    forbidden_fragments = [x.lower() for x in policy["forbidden_pregame_feature_fragments"]]
    features = list(runtime["features"])
    leakage_names = [
        feature
        for feature in features
        if any(fragment in feature.lower() for fragment in forbidden_fragments)
    ]
    if leakage_names:
        raise ValueError(f"Runtime schema contains forbidden pregame feature names: {leakage_names}")

    df = df.sort_values(["event_time", "event_id"], kind="stable").reset_index(drop=True)
    return df, features


def _portable_predict(
    artifact: dict[str, Any],
    values: np.ndarray,
) -> np.ndarray:
    model = artifact["portable_model"]
    x = np.asarray(values, dtype=float)
    imputer = np.asarray(model["imputer_median"], dtype=float)
    scaler_mean = np.asarray(model["scaler_mean"], dtype=float)
    scaler_scale = np.asarray(model["scaler_scale"], dtype=float)
    coef = np.asarray(model["logistic_coef"], dtype=float)
    intercept = float(model["logistic_intercept"])

    missing = np.isnan(x)
    if missing.any():
        x = x.copy()
        x[missing] = np.take(imputer, np.where(missing)[1])
    scale = np.where(scaler_scale == 0, 1.0, scaler_scale)
    z = (x - scaler_mean) / scale
    logits = z @ coef + intercept
    raw = 1.0 / (1.0 + np.exp(-np.clip(logits, -40, 40)))
    iso = IsotonicPortable(
        x=[float(v) for v in model["isotonic_x"]],
        y=[float(v) for v in model["isotonic_y"]],
    )
    return np.clip(iso.predict(raw), 1e-9, 1 - 1e-9)


def _extract_portable(
    fitted: Pipeline,
    calibrator: IsotonicPortable,
) -> dict[str, Any]:
    imputer: SimpleImputer = fitted.named_steps["imputer"]
    scaler: StandardScaler = fitted.named_steps["scaler"]
    model: LogisticRegression = fitted.named_steps["model"]
    return {
        "imputer_median": [float(x) for x in imputer.statistics_],
        "scaler_mean": [float(x) for x in scaler.mean_],
        "scaler_scale": [float(x) for x in scaler.scale_],
        "logistic_coef": [float(x) for x in model.coef_[0]],
        "logistic_intercept": float(model.intercept_[0]),
        "isotonic_x": calibrator.x,
        "isotonic_y": calibrator.y,
    }


def _sign_artifact(core: dict[str, Any], policy: dict[str, Any]) -> tuple[str, str] | None:
    private_b64 = os.getenv("MODEL_SIGNING_PRIVATE_KEY_B64", "").strip()
    if not private_b64:
        return None
    raw = base64.b64decode(private_b64)
    if len(raw) != 32:
        raise ValueError("MODEL_SIGNING_PRIVATE_KEY_B64 must decode to a 32-byte Ed25519 private seed")
    signature = Ed25519PrivateKey.from_private_bytes(raw).sign(_canonical(core))
    return (
        policy["artifact_policy"]["signing_key_id"],
        base64.b64encode(signature).decode("ascii"),
    )


def train(
    input_path: Path,
    sport: str,
    output_dir: Path,
) -> dict[str, Any]:
    policy = _load_policy()
    sport = sport.upper()
    if sport not in policy["sample_policy"]:
        raise ValueError(f"Unsupported sport: {sport}")

    raw = _read_table(input_path)
    df, features = _validate_and_sort(raw, sport, policy)
    sample_policy = policy["sample_policy"][sport]

    n = len(df)
    holdout_n = max(int(np.ceil(n * 0.20)), int(sample_policy["minimum_holdout_rows"]))
    if holdout_n >= n:
        holdout_n = max(1, int(np.ceil(n * 0.20)))
    dev = df.iloc[: n - holdout_n].copy()
    holdout = df.iloc[n - holdout_n :].copy()

    x_dev = dev[features].to_numpy(dtype=float)
    y_dev = dev["target_home_win"].to_numpy(dtype=int)

    oof_raw = np.full(len(dev), np.nan, dtype=float)
    split = TimeSeriesSplit(n_splits=5)
    fold_records: list[dict[str, Any]] = []
    for fold_index, (train_idx, valid_idx) in enumerate(split.split(x_dev), start=1):
        fold_model = _build_pipeline()
        fold_model.fit(x_dev[train_idx], y_dev[train_idx])
        fold_prob = fold_model.predict_proba(x_dev[valid_idx])[:, 1]
        oof_raw[valid_idx] = fold_prob
        fold_records.append(
            {
                "fold": fold_index,
                "train_rows": int(len(train_idx)),
                "valid_rows": int(len(valid_idx)),
                "train_end_event_time": dev.iloc[int(train_idx[-1])]["event_time"].isoformat(),
                "valid_start_event_time": dev.iloc[int(valid_idx[0])]["event_time"].isoformat(),
                "chronological": bool(
                    dev.iloc[int(train_idx[-1])]["event_time"]
                    < dev.iloc[int(valid_idx[0])]["event_time"]
                ),
                "preprocessing_fit_scope": "fold_train_only",
            }
        )

    oof_mask = ~np.isnan(oof_raw)
    oof_rows = int(oof_mask.sum())
    if oof_rows < 2 or len(np.unique(y_dev[oof_mask])) < 2:
        raise ValueError("OOF predictions are insufficient to fit calibration")
    calibrator = _fit_isotonic(oof_raw[oof_mask], y_dev[oof_mask])

    final_model = _build_pipeline()
    final_model.fit(x_dev, y_dev)

    x_holdout = holdout[features].to_numpy(dtype=float)
    y_holdout = holdout["target_home_win"].to_numpy(dtype=int)
    raw_holdout = final_model.predict_proba(x_holdout)[:, 1]
    candidate_holdout = np.clip(calibrator.predict(raw_holdout), 1e-9, 1 - 1e-9)
    baseline_holdout = holdout["market_home_probability"].to_numpy(dtype=float)

    candidate_metrics = _metrics(y_holdout, candidate_holdout)
    baseline_metrics = _metrics(y_holdout, baseline_holdout)
    oof_metrics = _metrics(y_dev[oof_mask], calibrator.predict(oof_raw[oof_mask]))

    source_sha = _sha256_file(input_path)
    schema_payload = {
        "schema_version": 1,
        "sport": sport,
        "features": features,
        "target": policy["runtime_schema"]["target"],
        "dtypes": {feature: "float64" for feature in features},
    }
    schema_sha = _sha256_bytes(_canonical(schema_payload))

    core = {
        "artifact_format": policy["artifact_policy"]["format"],
        "schema_version": 1,
        "sport": sport,
        "status": "CANDIDATE",
        "trained_weights": True,
        "model_id": f"{sport.lower()}-logistic-isotonic-{source_sha[:12]}",
        "features": features,
        "feature_schema": schema_payload,
        "portable_model": _extract_portable(final_model, calibrator),
        "promotion_evidence": {
            "sample_sufficiency": {
                "total_rows": n,
                "development_rows": int(len(dev)),
                "oof_rows": oof_rows,
                "holdout_rows": int(len(holdout)),
                "minimum_total_rows": int(sample_policy["minimum_total_rows"]),
                "minimum_oof_rows": int(sample_policy["minimum_oof_rows"]),
                "minimum_holdout_rows": int(sample_policy["minimum_holdout_rows"]),
            },
            "chronology": {
                "as_of_lt_event_time": True,
                "walk_forward_oof": bool(all(x["chronological"] for x in fold_records)),
                "folds": fold_records,
                "development_end": dev.iloc[-1]["event_time"].isoformat(),
                "holdout_start": holdout.iloc[0]["event_time"].isoformat(),
            },
            "calibration": {
                "method": policy["metric_policy"]["calibration_method"],
                "oof_only": True,
                "oof_metrics": oof_metrics,
                "brier": candidate_metrics["brier"],
                "log_loss": candidate_metrics["log_loss"],
                "ece": candidate_metrics["ece"],
            },
            "holdout": {
                "separate_from_calibration": True,
                "resolved_games": int(len(holdout)),
                "candidate_metrics": candidate_metrics,
                "market_baseline_metrics": baseline_metrics,
            },
            "leakage_audit": {
                "passed": True,
                "forbidden_feature_fragments_checked": policy["forbidden_pregame_feature_fragments"],
                "runtime_features": features,
            },
            "market_baseline_comparison": {
                "candidate_brier": candidate_metrics["brier"],
                "baseline_brier": baseline_metrics["brier"],
                "brier_improvement": baseline_metrics["brier"] - candidate_metrics["brier"],
                "candidate_log_loss": candidate_metrics["log_loss"],
                "baseline_log_loss": baseline_metrics["log_loss"],
            },
            "provenance": {
                "dataset_sha256": source_sha,
                "feature_schema_sha256": schema_sha,
                "source_manifest_sha256": source_sha,
            },
        },
    }

    portable_prob = _portable_predict(core, x_holdout)
    parity_max_abs = float(np.max(np.abs(portable_prob - candidate_holdout)))
    parity_cases = []
    for idx in range(min(32, len(holdout))):
        parity_cases.append(
            {
                "event_id": str(holdout.iloc[idx]["event_id"]),
                "features": [
                    None if np.isnan(v) else float(v)
                    for v in x_holdout[idx]
                ],
                "expected_probability": float(candidate_holdout[idx]),
            }
        )
    core["mobile_parity"] = {
        "source": "untouched_chronological_holdout",
        "case_count": len(parity_cases),
        "max_abs_error_python_portable_vs_sklearn": parity_max_abs,
        "cases": parity_cases,
    }

    metric_policy = policy["metric_policy"]
    checks = {
        "minimum_total_rows": n >= int(sample_policy["minimum_total_rows"]),
        "minimum_oof_rows": oof_rows >= int(sample_policy["minimum_oof_rows"]),
        "minimum_holdout_rows": len(holdout) >= int(sample_policy["minimum_holdout_rows"]),
        "chronological_folds": all(x["chronological"] for x in fold_records),
        "brier_improvement": (
            baseline_metrics["brier"] - candidate_metrics["brier"]
            >= float(metric_policy["minimum_brier_improvement"])
        ),
        "log_loss_non_inferior": (
            candidate_metrics["log_loss"]
            <= baseline_metrics["log_loss"] + float(metric_policy["maximum_log_loss_regression"])
        ),
        "ece": candidate_metrics["ece"] <= float(metric_policy["ece_max"]),
        "no_leakage": True,
        "schema_compatible": features == list(policy["runtime_schema"]["features"]),
        "portable_parity": parity_max_abs <= 1e-10,
    }

    unsigned_sha = _sha256_bytes(_canonical(core))
    core["promotion_evidence"]["provenance"]["model_sha256"] = unsigned_sha
    signature = _sign_artifact(core, policy)
    checks["artifact_signed"] = signature is not None
    passed = all(checks.values())

    core["promotion_checks"] = checks
    core["status"] = "PROMOTED_TRAINED_MODEL" if passed else "CANDIDATE_REJECTED"
    core["promotion_evidence"]["market_baseline_comparison"]["passed"] = bool(
        checks["brier_improvement"] and checks["log_loss_non_inferior"]
    )
    core["promotion_evidence"]["provenance"]["artifact_sha256"] = _sha256_bytes(_canonical(core))

    artifact = dict(core)
    if signature is not None:
        key_id, sig_b64 = signature
        artifact["signature"] = {
            "algorithm": "ed25519",
            "key_id": key_id,
            "signature_b64": sig_b64,
            "signed_core_sha256": unsigned_sha,
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = output_dir / f"{sport.lower()}-candidate.json"
    candidate_path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    report = {
        "sport": sport,
        "input": str(input_path),
        "candidate_path": str(candidate_path),
        "promotion_passed": passed,
        "checks": checks,
        "candidate_metrics": candidate_metrics,
        "baseline_metrics": baseline_metrics,
        "artifact_sha256": _sha256_file(candidate_path),
    }
    (output_dir / f"{sport.lower()}-promotion-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PhilthySports chronological walk-forward training and promotion gate"
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--sport", required=True, choices=["NFL", "NBA", "MLB", "NHL"])
    parser.add_argument("--output-dir", type=Path, default=Path("backend/models/candidates"))
    args = parser.parse_args()
    report = train(args.input, args.sport, args.output_dir)
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit(0 if report["promotion_passed"] else 2)


if __name__ == "__main__":
    main()
