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
        core_sha == artifact.get("artifact_core_sha256")
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
    security["model_checksum_verified"] = (
        sha256_json(artifact.get("portable_model") or {})
        == provenance.get("model_sha256")
    )
    security["schema_checksum_verified"] = (
        sha256_json(artifact.get("feature_schema") or {})
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

    brier_improvement = baseline.get("brier_improvement")
    candidate_log_loss = baseline.get("candidate_log_loss")
    baseline_log_loss = baseline.get("baseline_log_loss")
    ece = calibration.get("ece")

    features = artifact.get("features") or []
    expected_features = policy["runtime_schema"]["features"]
    checks = {
        "sport_matches": artifact.get("sport") == sport,
        "trained_weights": artifact.get("trained_weights") is True,
        "sample_total": int(samples.get("total_rows") or 0) >= int(minimums["minimum_total_rows"]),
        "sample_oof": int(samples.get("oof_rows") or 0) >= int(minimums["minimum_oof_rows"]),
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
            isinstance((artifact.get("mobile_parity") or {}).get("max_abs_error_python_portable_vs_sklearn"), (int, float))
            and float(artifact["mobile_parity"]["max_abs_error_python_portable_vs_sklearn"]) <= 1e-10
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
    features = artifact["features"]
    model = artifact["portable_model"]
    values = []
    for index, feature in enumerate(features):
        raw = feature_values.get(feature)
        value = float(model["imputer_median"][index]) if raw is None else float(raw)
        mean = float(model["scaler_mean"][index])
        scale = float(model["scaler_scale"][index]) or 1.0
        values.append((value - mean) / scale)

    logit = float(model["logistic_intercept"])
    for coefficient, value in zip(model["logistic_coef"], values):
        logit += float(coefficient) * value
    raw_probability = 1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, logit))))

    xs = [float(x) for x in model["isotonic_x"]]
    ys = [float(y) for y in model["isotonic_y"]]
    if not xs:
        return raw_probability
    if raw_probability <= xs[0]:
        return ys[0]
    if raw_probability >= xs[-1]:
        return ys[-1]
    for idx in range(1, len(xs)):
        if raw_probability <= xs[idx]:
            x0, x1 = xs[idx - 1], xs[idx]
            y0, y1 = ys[idx - 1], ys[idx]
            if x1 == x0:
                return y1
            ratio = (raw_probability - x0) / (x1 - x0)
            return y0 + ratio * (y1 - y0)
    return ys[-1]
