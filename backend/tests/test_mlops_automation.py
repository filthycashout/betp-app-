import json
from pathlib import Path

import pytest

from training.data_contract import validate_records
from training.register_artifact import _canonical, _sha256, register


def _canonical_row(**overrides):
    row = {
        "sport": "NFL",
        "event_id": "evt-1",
        "event_time": "2026-10-20T01:00:00Z",
        "as_of": "2026-10-19T20:00:00Z",
        "home_team": "A",
        "away_team": "B",
        "market_home_probability": 0.55,
        "target_home_win": 1,
        "label_available_at": "2026-10-20T05:00:00Z",
        "consensus_de_vig_home_probability": 0.55,
        "home_spread": -2.5,
        "consensus_total": 45.5,
    }
    row.update(overrides)
    return row


def test_contract_accepts_chronological_canonical_row():
    result = validate_records(
        [_canonical_row()],
        mode="canonical",
        sport="NFL",
        features=[
            "consensus_de_vig_home_probability",
            "home_spread",
            "consensus_total",
        ],
    )
    assert result["status"] == "PASS"


def test_contract_rejects_post_start_snapshot():
    with pytest.raises(ValueError):
        validate_records(
            [_canonical_row(as_of="2026-10-20T02:00:00Z")],
            mode="canonical",
            sport="NFL",
            features=[],
        )


def test_contract_rejects_duplicate_event_keys():
    with pytest.raises(ValueError):
        validate_records(
            [_canonical_row(), _canonical_row()],
            mode="canonical",
            sport="NFL",
            features=[],
        )


def test_registry_is_content_addressed_and_idempotent(tmp_path: Path):
    artifact = {
        "schema_version": 3,
        "sport": "NFL",
        "model_id": "m1",
        "model_type": "logistic",
        "status": "PROMOTED_TRAINED_MODEL",
        "promotion_evidence": {
            "provenance": {
                "dataset_sha256": "a" * 64,
                "feature_schema_sha256": "b" * 64,
            }
        },
    }
    artifact["artifact_sha256"] = _sha256(_canonical(artifact))
    artifact["signature"] = {
        "signed_core_sha256": _sha256(_canonical(artifact)),
        "key_id": "key",
        "public_key_b64": "pub",
        "signature_b64": "sig",
    }

    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")

    first = register(artifact_path, tmp_path / "registry", "NFL")
    second = register(artifact_path, tmp_path / "registry", "NFL")
    assert first["artifact_sha256"] == second["artifact_sha256"]

    index = json.loads((tmp_path / "registry" / "index.json").read_text())
    assert len(index["sports"]["NFL"]["artifacts"]) == 1
    assert index["sports"]["NFL"]["active"] == artifact["artifact_sha256"]
    assert (
        tmp_path
        / "registry"
        / "nfl"
        / f"{artifact['artifact_sha256']}.json"
    ).exists()
