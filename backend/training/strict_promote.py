from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np

import governed_train as base


POLICY = json.loads((Path(__file__).resolve().parent / "policy.json").read_text())


def source_quarantine_reasons(manifest: dict) -> list[str]:
    """Honor explicit upstream holds; absence is not independent verification.

    The existing checksum and provenance checks still apply. This guard only
    prevents a research/held source from being promoted despite its own flags.
    """
    flags = (
        "promotion_ready", "promotion_eligible",
        "independent_publication_timestamp_verified",
    )
    return [f"{name}=false" for name in flags if manifest.get(name) is False]


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sigmoid(value: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(value, -40.0, 40.0)))


def _portable_isotonic(raw: np.ndarray, cal: dict) -> np.ndarray:
    xs = np.asarray(cal.get("x_thresholds") or [], dtype=float)
    ys = np.asarray(cal.get("y_thresholds") or [], dtype=float)
    if not len(xs) or len(xs) != len(ys):
        raise ValueError("portable isotonic thresholds are missing or misaligned")
    return np.interp(np.asarray(raw, dtype=float), xs, ys, left=ys[0], right=ys[-1])


def portable_predict(artifact: dict, matrix: np.ndarray) -> np.ndarray:
    prep = artifact["preprocessing"]
    prob = artifact["probability"]

    x = np.asarray(matrix, dtype=float).copy()
    medians = np.asarray(prep["imputer_statistics"], dtype=float)
    means = np.asarray(prep["standard_scaler_mean"], dtype=float)
    scales = np.asarray(prep["standard_scaler_scale"], dtype=float)
    coefs = np.asarray(prob["coefficients"], dtype=float)
    intercept = float(prob["intercept"])

    missing = np.isnan(x)
    if missing.any():
        rows, cols = np.where(missing)
        x[rows, cols] = medians[cols]

    z = (x - means) / np.where(scales == 0.0, 1.0, scales)
    raw = _sigmoid(z @ coefs + intercept)

    cal = prob["calibrator"]
    calibration_type = cal.get("type")
    if calibration_type == "platt_logit_logistic":
        clipped = np.clip(raw, 1e-6, 1 - 1e-6)
        logits = np.log(clipped / (1.0 - clipped))
        return _sigmoid(
            logits * float(cal["coefficient"]) + float(cal["intercept"])
        )
    if calibration_type == "isotonic":
        return _portable_isotonic(raw, cal)
    raise ValueError(f"unsupported portable calibration type: {calibration_type}")


def _server_calibrated_probability(local_model: dict, raw: np.ndarray) -> np.ndarray:
    method = str(local_model.get("calibration_method") or "platt")
    calibrator = local_model["calibrator"]
    if method == "platt":
        clipped = np.clip(raw, 1e-6, 1 - 1e-6)
        logits = np.log(clipped / (1.0 - clipped)).reshape(-1, 1)
        return calibrator.predict_proba(logits)[:, 1]
    if method == "isotonic":
        return np.asarray(calibrator.predict(raw), dtype=float)
    raise ValueError(f"unsupported server calibration method: {method}")


def enforce(args: argparse.Namespace) -> dict:
    report = base.run(args)
    source_manifest = json.loads(Path(args.source_manifest).read_text())
    quarantine_reasons = source_quarantine_reasons(source_manifest)
    sport = args.sport.upper()
    min_policy = POLICY["sample_policy"][sport]
    metric_policy = POLICY["metric_policy"]

    artifact_path = Path(report["mobile_artifact"])
    joblib_path = Path(report["server_joblib"])
    artifact = json.loads(artifact_path.read_text())
    dataset, features, provenance = base.load_canonical(
        Path(args.input),
        [x.strip() for x in args.features.split(",") if x.strip()]
        if args.features
        else None,
    )

    holdout_rows = int(report["holdout_rows"])
    _, holdout = base.chronological_holdout(dataset, args.holdout_fraction)
    oof_rows = int(report["oof_rows"])

    local_model = joblib.load(joblib_path)
    server_raw = local_model["pipeline"].predict_proba(holdout[features])[:, 1]
    server_prob = _server_calibrated_probability(local_model, server_raw)
    portable_prob = portable_predict(
        artifact,
        holdout[features].to_numpy(dtype=float),
    )
    parity_max_abs = float(np.max(np.abs(server_prob - portable_prob)))

    candidate = report["candidate_metrics"]
    market = report["market_metrics"]
    brier_improvement = float(market["brier"]) - float(candidate["brier"])
    allowed_logloss_regression = float(metric_policy["maximum_log_loss_regression"])
    calibration = artifact.get("promotion_evidence", {}).get("calibration", {})
    selection = calibration.get("method_selection") or {}
    selected_method = selection.get("selected_method")
    artifact_calibrator = artifact.get("probability", {}).get("calibrator", {})
    expected_type = {
        "platt": "platt_logit_logistic",
        "isotonic": "isotonic",
    }.get(selected_method)

    strict_checks = {
        "minimum_total_rows": int(report["dataset_rows"]) >= int(min_policy["minimum_total_rows"]),
        "minimum_oof_rows": oof_rows >= int(min_policy["minimum_oof_rows"]),
        "minimum_holdout_rows": holdout_rows >= int(min_policy["minimum_holdout_rows"]),
        "chronology": bool(report["promotion_checks"].get("chronology")),
        "walk_forward_oof": bool(report["promotion_checks"].get("walk_forward_oof")),
        "label_availability": artifact["promotion_evidence"]["chronology"].get("labels_available_before_validation") is True,
        "simultaneous_predictions_grouped": artifact["promotion_evidence"]["chronology"].get("simultaneous_predictions_grouped") is True,
        "in_fold_preprocessing": (
            artifact.get("preprocessing", {}).get("fit_scope")
            == "final_pre_holdout_training_only"
            and artifact.get("promotion_evidence", {})
            .get("chronology", {})
            .get("in_fold_preprocessing") is True
        ),
        "calibration_oof_only": (
            artifact_calibrator.get("fit_source")
            == "chronological_out_of_fold_predictions_only"
        ),
        "calibration_method_selection": (
            selected_method in {"platt", "isotonic"}
            and artifact_calibrator.get("type") == expected_type
            and int(selection.get("validation_rows") or 0) > 0
            and artifact.get("promotion_evidence", {})
            .get("holdout", {})
            .get("untouched_during_method_selection") is True
        ),
        "separate_holdout": (
            artifact.get("promotion_evidence", {})
            .get("holdout", {})
            .get("separate_from_calibration") is True
        ),
        "brier_improvement": brier_improvement >= float(metric_policy["minimum_brier_improvement"]),
        "log_loss_non_inferior": (
            float(candidate["log_loss"])
            <= float(market["log_loss"]) + allowed_logloss_regression
        ),
        "ece_threshold": float(candidate["ece"]) <= float(metric_policy["ece_max"]),
        "no_leakage": bool(report["promotion_checks"].get("leakage_audit")),
        "schema_compatible": list(features) == list(POLICY["runtime_schema"]["features"]),
        "dataset_checksum": bool(report.get("dataset_sha256")),
        "feature_schema_checksum": (
            bool(report.get("feature_schema_sha256"))
            and report.get("feature_schema_sha256") == provenance["feature_schema_sha256"]
        ),
        "source_manifest_checksum": bool(report.get("source_manifest_sha256")),
        "source_not_quarantined": not quarantine_reasons,
        "portable_parity": parity_max_abs <= 1e-10,
    }
    eligible = all(strict_checks.values())

    evidence = artifact.setdefault("promotion_evidence", {})
    evidence["strict_policy"] = {
        "policy_sha256": _sha256((Path(__file__).resolve().parent / "policy.json").read_bytes()),
        "checks": strict_checks,
        "minimums": min_policy,
        "metric_policy": metric_policy,
        "brier_improvement": brier_improvement,
        "oof_rows": oof_rows,
    }
    artifact["mobile_parity"] = {
        "source": "untouched_chronological_holdout",
        "case_count": len(holdout),
        "max_abs_error": parity_max_abs,
        "tolerance": 1e-10,
    }
    artifact["status"] = "PROMOTION_ELIGIBLE_UNSIGNED" if eligible else "CANDIDATE_REJECTED"
    artifact.pop("signature", None)
    artifact["artifact_sha256"] = _sha256(
        _canonical({k: v for k, v in artifact.items() if k != "artifact_sha256"})
    )
    artifact_path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")

    report["strict_policy_pass"] = eligible
    report["source_quarantine_reasons"] = quarantine_reasons
    report["strict_checks"] = strict_checks
    report["brier_improvement"] = brier_improvement
    report["oof_rows"] = oof_rows
    report["mobile_parity_max_abs_error"] = parity_max_abs
    report["status"] = artifact["status"]
    report["mobile_artifact_sha256"] = _sha256(artifact_path.read_bytes())
    Path(report["mobile_artifact"]).with_name(
        f"{sport.lower()}_strict_promotion_report.json"
    ).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", required=True, choices=["NFL", "NBA", "MLB", "NHL"])
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--features")
    parser.add_argument("--splits", type=int, default=5)
    parser.add_argument("--holdout-fraction", type=float, default=0.20)
    parser.add_argument("--min-rows", type=int)
    parser.add_argument("--logloss-margin", type=float, default=0.0)
    args = parser.parse_args()
    result = enforce(args)
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["strict_policy_pass"] else 2)


if __name__ == "__main__":
    main()
