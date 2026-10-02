from __future__ import annotations

import base64
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


HERE = Path(__file__).resolve().parent
POLICY = json.loads((HERE / "training" / "policy.json").read_text())
PROMOTED_DIR = HERE / "models" / "promoted"


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _signature_core(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in artifact.items()
        if key not in {"signature", "effective_status", "artifact_core_sha256", "runtime_security"}
    }


def verify_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    policy = POLICY
    security = {
        "signature_verified": False,
        "core_checksum_verified": False,
        "model_checksum_verified": False,
        "schema_checksum_verified": False,
        "signing_key_id_verified": False,
    }

    signature = artifact.get("signature") or {}
    core = _signature_core(artifact)
    core_sha = sha256_json(core)
    security["core_checksum_verified"] = (
        bool(signature.get("signed_core_sha256"))
        and core_sha == signature.get("signed_core_sha256")
    )

    expected_key_id = policy["artifact_policy"]["signing_key_id"]
    security["signing_key_id_verified"] = signature.get("key_id") == expected_key_id

    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(policy["artifact_policy"]["signing_public_key_b64"])
        )
        public_key.verify(
            base64.b64decode(signature.get("signature_b64") or ""),
            canonical_json(core),
        )
        security["signature_verified"] = True
    except (ValueError, TypeError, InvalidSignature):
        security["signature_verified"] = False

    evidence = artifact.get("promotion_evidence") or {}
    provenance = evidence.get("provenance") or {}
    model_core = {
        "features": artifact.get("features") or [],
        "preprocessing": artifact.get("preprocessing") or {},
        "probability": artifact.get("probability") or {},
    }
    security["model_checksum_verified"] = (
        bool(provenance.get("model_sha256"))
        and sha256_json(model_core) == provenance.get("model_sha256")
    )
    security["schema_checksum_verified"] = (
        bool(provenance.get("feature_schema_sha256"))
        and sha256_json(evidence.get("schema") or {})
        == provenance.get("feature_schema_sha256")
    )
    security["passed"] = all(security.values())
    return security


def promotion_gate(artifact: dict[str, Any], sport: str) -> dict[str, Any]:
    sport = sport.upper()
    policy = POLICY
    evidence = artifact.get("promotion_evidence") or {}
    samples = evidence.get("sample_sufficiency") or {}
    chronology = evidence.get("chronology") or {}
    calibration = evidence.get("calibration") or {}
    holdout = evidence.get("holdout") or {}
    leakage = evidence.get("leakage_audit") or {}
    baseline = evidence.get("market_baseline_comparison") or {}
    provenance = evidence.get("provenance") or {}
    minimums = policy["sample_policy"][sport]
    security = verify_artifact(artifact)

    strict = evidence.get("strict_policy") or {}
    brier_improvement = strict.get("brier_improvement")
    if not isinstance(brier_improvement, (int, float)):
        candidate_brier = baseline.get("candidate_brier")
        market_brier = baseline.get("market_brier")
        if isinstance(candidate_brier, (int, float)) and isinstance(market_brier, (int, float)):
            brier_improvement = float(market_brier) - float(candidate_brier)
    candidate_log_loss = baseline.get("candidate_log_loss")
    baseline_log_loss = baseline.get("market_log_loss")
    ece = calibration.get("ece")

    features = artifact.get("features") or []
    expected_features = policy["runtime_schema"]["features"]
    checks = {
        "sport_matches": artifact.get("sport") == sport,
        "trained_weights": artifact.get("trained_weights") is True,
        "sample_total": int(samples.get("rows") or 0) >= int(minimums["minimum_total_rows"]),
        "sample_oof": int(strict.get("oof_rows") or 0) >= int(minimums["minimum_oof_rows"]),
        "sample_holdout": int(samples.get("holdout_rows") or 0) >= int(minimums["minimum_holdout_rows"]),
        "chronology_as_of_before_event": chronology.get("as_of_lt_event_time") is True,
        "walk_forward_oof": chronology.get("walk_forward_oof") is True,
        "calibration_oof_only": calibration.get("oof_only") is True,
        "separate_holdout": holdout.get("separate_from_calibration") is True,
        "brier_improvement": (
            isinstance(brier_improvement, (int, float))
            and float(brier_improvement) >= float(policy["metric_policy"]["minimum_brier_improvement"])
        ),
        "log_loss_non_inferior": (
            isinstance(candidate_log_loss, (int, float))
            and isinstance(baseline_log_loss, (int, float))
            and float(candidate_log_loss)
            <= float(baseline_log_loss) + float(policy["metric_policy"]["maximum_log_loss_regression"])
        ),
        "ece_threshold": (
            isinstance(ece, (int, float))
            and float(ece) <= float(policy["metric_policy"]["ece_max"])
        ),
        "leakage_audit": leakage.get("passed") is True,
        "schema_compatible": list(features) == list(expected_features),
        "dataset_provenance": bool(provenance.get("dataset_sha256")),
        "source_provenance": bool(provenance.get("source_manifest_sha256")),
        "signature_verified": security["signature_verified"],
        "core_checksum_verified": security["core_checksum_verified"],
        "model_checksum_verified": security["model_checksum_verified"],
        "schema_checksum_verified": security["schema_checksum_verified"],
        "signing_key_id_verified": security["signing_key_id_verified"],
        "mobile_parity": (
            isinstance((artifact.get("mobile_parity") or {}).get("max_abs_error"), (int, float))
            and float(artifact["mobile_parity"]["max_abs_error"]) <= 1e-10
            and int((artifact.get("mobile_parity") or {}).get("case_count") or 0) > 0
        ),
    }
    passed = all(checks.values())
    return {
        "sport": sport,
        "passed": passed,
        "checks": checks,
        "security": security,
        "evidence": evidence,
        "runtime_role": "PROMOTED_TRAINED_MODEL" if passed else "BASELINE_FALLBACK",
    }


def load_promoted(sport: str) -> dict[str, Any] | None:
    path = PROMOTED_DIR / f"{sport.lower()}.json"
    if not path.exists():
        return None
    try:
        artifact = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    gate = promotion_gate(artifact, sport)
    if not gate["passed"]:
        return None
    artifact["runtime_security"] = gate["security"]
    return artifact


def predict_home_probability(artifact: dict[str, Any], feature_values: dict[str, float | None]) -> float:
    features = list(artifact.get("features") or [])
    prep = artifact.get("preprocessing") or {}
    prob = artifact.get("probability") or {}

    medians = list(prep.get("imputer_statistics") or [])
    means = list(prep.get("standard_scaler_mean") or [])
    scales = list(prep.get("standard_scaler_scale") or [])
    coefs = list(prob.get("coefficients") or [])
    if not (len(features) == len(medians) == len(means) == len(scales) == len(coefs)):
        raise ValueError("portable model vector lengths do not match")

    values = []
    for index, feature in enumerate(features):
        raw = feature_values.get(feature)
        value = float(medians[index]) if raw is None else float(raw)
        scale = float(scales[index]) or 1.0
        values.append((value - float(means[index])) / scale)

    raw_logit = float(prob.get("intercept") or 0.0)
    for coefficient, value in zip(coefs, values):
        raw_logit += float(coefficient) * value
    raw_probability = 1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, raw_logit))))

    clipped = max(1e-6, min(1.0 - 1e-6, raw_probability))
    logit_value = math.log(clipped / (1.0 - clipped))
    calibrator = prob.get("calibrator") or {}
    calibrated_logit = (
        logit_value * float(calibrator.get("coefficient") or 0.0)
        + float(calibrator.get("intercept") or 0.0)
    )
    return 1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, calibrated_logit))))
