import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from training import data_contract as dc
from training import enrich_capture_contract as enrich
from training import recovery_manifest as recovery
from training import settlement_proof as proof


def test_contract_v2_accepts_bound_pregame_market():
    row = {
        "schema_version": "2",
        "sport": "NFL",
        "event_id": "evt",
        "event_time": "2026-10-18T20:00:00Z",
        "event_started_at": "2026-10-18T20:00:00Z",
        "as_of": "2026-10-18T18:00:00Z",
        "quote_captured_at": "2026-10-18T18:00:00Z",
        "home_team": "Home",
        "away_team": "Away",
        "market_type": "moneyline",
        "selection": "Home",
        "market_home_probability": 0.55,
        "raw_snapshot_sha256": "a" * 64,
    }
    assert dc.validate_records([row], mode="pregame", sport="NFL", features=[])["status"] == "PASS"


def test_contract_v2_rejects_quote_at_or_after_start():
    row = {
        "sport": "NBA", "event_id": "evt", "event_time": "2026-10-18T20:00:00Z",
        "event_started_at": "2026-10-18T20:00:00Z", "as_of": "2026-10-18T19:00:00Z",
        "quote_captured_at": "2026-10-18T20:00:00Z", "home_team": "H", "away_team": "A",
    }
    with pytest.raises(ValueError, match="market chronology"):
        dc.validate_records([row], mode="pregame", sport="NBA", features=[])


def test_canonical_scores_must_match_target():
    row = {
        "sport": "NHL", "event_id": "evt", "event_time": "2026-10-18T20:00:00Z",
        "as_of": "2026-10-18T18:00:00Z", "home_team": "H", "away_team": "A",
        "target_home_win": 1, "label_available_at": "2026-10-18T23:00:00Z",
        "final_home_score": 1, "final_away_score": 4,
    }
    with pytest.raises(ValueError, match="final scores disagree"):
        dc.validate_records([row], mode="canonical", sport="NHL", features=[])


def test_recovery_manifest_never_promotes_legacy_model_or_feature_snapshot(tmp_path):
    source = tmp_path / "source.json"
    source.write_text(json.dumps({
        "sports": {
            "MLB": {"sources": [
                {"title": "daily.parquet", "sha256": "a" * 64, "role": "feature_snapshot"},
                {"title": "model.joblib", "sha256": "b" * 64, "role": "quarantined_serialized_model"},
                {"title": "results.csv", "sha256": "c" * 64, "role": "settled_evaluation"},
            ]}
        },
        "excluded_placeholder_folders": [{"title": "Models", "status": "EMPTY"}],
    }))
    result = recovery.build(source)
    classes = {item["title"]: item["classification"] for item in result["entries"]}
    assert classes["daily.parquet"] == "FEATURE_REFERENCE"
    assert classes["model.joblib"] == "MODEL_REFERENCE"
    assert classes["results.csv"] == "SETTLEMENT_ONLY"
    assert classes["Models"] == "EMPTY"
    assert "ADMISSIBLE_PREGAME" not in classes.values()


def test_recovery_manifest_marks_duplicate_hashes(tmp_path):
    source = tmp_path / "source.json"
    source.write_text(json.dumps({"sports": {"NFL": {"sources": [
        {"title": "a.txt", "sha256": "d" * 64, "role": "tracking_metadata"},
        {"title": "copy.txt", "sha256": "d" * 64, "role": "tracking_metadata"},
    ]}}}))
    result = recovery.build(source)
    assert [x["classification"] for x in result["entries"]] == ["ARCHIVE_ONLY", "DUPLICATE"]


def test_capture_enrichment_binds_raw_hash_without_synthesizing_market_id(tmp_path):
    raw = tmp_path / "powerhouse_raw_x.json"
    raw.write_text(json.dumps({"payload": {"games": [{
        "sport": "NFL", "event_id": "evt", "home": "H", "market_source": "provider",
        "market": {"home_probability": 0.55, "moneyline_pick": "H", "moneyline_best_price": -120, "moneyline_best_book": "book"},
    }]}}))
    rows = tmp_path / "pregame_x.jsonl"
    rows.write_text(json.dumps({
        "sport": "NFL", "event_id": "evt", "event_time": "2026-10-18T20:00:00+00:00",
        "as_of": "2026-10-18T18:00:00+00:00", "home_team": "H", "away_team": "A",
        "market_home_probability": 0.55,
    }) + "\n")
    manifest = tmp_path / "manifest_x.json"
    manifest.write_text(json.dumps({
        "schema_version": 1,
        "raw_file": {"name": raw.name, "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(), "bytes": raw.stat().st_size},
        "rows_file": {"name": rows.name, "sha256": hashlib.sha256(rows.read_bytes()).hexdigest(), "bytes": rows.stat().st_size, "rows": 1},
    }))
    result = enrich.enrich(tmp_path)
    assert result["status"] == "PASS"
    row = json.loads(rows.read_text().strip())
    assert row["schema_version"] == "2"
    assert row["provider_market_id"] is None
    assert row["american_price"] == -120
    assert row["raw_snapshot_sha256"] == hashlib.sha256(raw.read_bytes()).hexdigest()
    assert json.loads(manifest.read_text())["data_contract_version"] == "2"


def test_official_settlement_proof_hashes_provider_event(monkeypatch):
    monkeypatch.setattr(proof, "_json", lambda _url: {"events": [{
        "id": "evt", "status": {"type": {"completed": True}},
        "competitions": [{"competitors": [
            {"homeAway": "home", "score": "24"}, {"homeAway": "away", "score": "17"}
        ]}],
    }]})
    result = proof._espn("NFL", datetime(2026, 10, 18, tzinfo=timezone.utc).date())["evt"]
    assert result["target_home_win"] == 1
    assert result["final_home_score"] == 24.0
    assert len(result["settlement_payload_sha256"]) == 64
