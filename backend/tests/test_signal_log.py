from datetime import datetime, timedelta, timezone

import pytest

from evidence.signal_log import (
    anchor_batch,
    make_signal,
    verify_merkle_proof,
    verify_signal,
)


def _signal(index: int):
    now = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc) + timedelta(seconds=index)
    return make_signal(
        match_id=f"NFL-{index}",
        league="NFL",
        season="2026",
        home_team="Home",
        away_team="Away",
        snapshot_time_utc=now,
        event_time_utc=now + timedelta(hours=3),
        data_latency_ms=100 + index,
        market_type="moneyline",
        selection="Home",
        line=None,
        odds_decimal=1.91,
        raw_probability=0.56,
        calibrated_probability=0.54,
        engine_version="philthy-v8-test",
        model_family="governed_logreg_isotonic",
        reason_codes=["promoted_model", "fresh_market_quote"],
        model_id="nfl-test",
        model_artifact_sha256="a" * 64,
        dataset_sha256="b" * 64,
        feature_schema_sha256="c" * 64,
        source="test-book",
        source_observed_at_utc=now - timedelta(seconds=1),
        signal_id=f"00000000-0000-4000-8000-{index:012d}",
    )


def test_signal_hash_detects_mutation():
    row = _signal(1)
    assert verify_signal(row)
    row["selection"] = "Away"
    assert not verify_signal(row)


def test_chronology_gate_rejects_post_kickoff_snapshot():
    now = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="Chronology violation"):
        make_signal(
            match_id="x",
            league="NFL",
            season="2026",
            home_team="Home",
            away_team="Away",
            snapshot_time_utc=now,
            event_time_utc=now,
            data_latency_ms=1,
            market_type="moneyline",
            selection="Home",
            line=None,
            odds_decimal=1.9,
            raw_probability=0.5,
            calibrated_probability=0.5,
            engine_version="test",
            model_family="test",
            reason_codes=["test"],
        )


def test_source_observation_must_not_be_after_snapshot():
    now = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="Source observation"):
        make_signal(
            match_id="x",
            league="NFL",
            season="2026",
            home_team="Home",
            away_team="Away",
            snapshot_time_utc=now,
            event_time_utc=now + timedelta(hours=1),
            data_latency_ms=1,
            market_type="moneyline",
            selection="Home",
            line=None,
            odds_decimal=1.9,
            raw_probability=0.5,
            calibrated_probability=0.5,
            engine_version="test",
            model_family="test",
            reason_codes=["test"],
            source_observed_at_utc=now + timedelta(seconds=1),
        )


def test_merkle_proofs_verify_for_every_leaf():
    anchored, manifest = anchor_batch([_signal(1), _signal(2), _signal(3)])
    assert manifest["leaf_count"] == 3
    for row in anchored:
        assert verify_signal(row)
        assert verify_merkle_proof(
            row["record_sha256"],
            row["merkle_proof"],
            row["merkle_root"],
        )
