from datetime import datetime, timedelta, timezone

from evidence import runtime
from evidence.signal_log import verify_merkle_proof, verify_signal


def test_search_payload_gets_immutable_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "SIGNAL_ROOT", tmp_path)
    now = datetime.now(timezone.utc)
    payload = {
        "version": "1.6.3-test",
        "games": [
            {
                "event_id": "401000001",
                "sport": "NFL",
                "home": "Home Team",
                "away": "Away Team",
                "event_time": (now + timedelta(hours=3)).isoformat(),
                "pick": "Home Team",
                "home_win_probability": 0.57,
                "probability_source": "fresh_de_vigged_consensus_moneyline",
                "predictions": {
                    "moneyline": {
                        "pick": "Home Team",
                        "home_win_probability": 0.57,
                        "source": "fresh_de_vigged_consensus_moneyline",
                    }
                },
                "market": {
                    "freshness_verified": True,
                    "moneyline_best_price": -110,
                    "moneyline_last_update": (now - timedelta(seconds=2)).isoformat(),
                },
                "model_metadata": {
                    "model_id": "nfl-market-baseline",
                    "model_type": "market_baseline",
                    "sha256": "a" * 64,
                    "promotion_gate": {
                        "passed": False,
                        "evidence": {
                            "provenance": {
                                "dataset_sha256": "b" * 64,
                                "feature_schema_sha256": "c" * 64,
                            }
                        },
                    },
                },
            }
        ],
    }

    result = runtime.record_search_payload(payload, data_latency_ms=123)
    evidence = result["games"][0]["evidence"]
    assert evidence["status"] == "RECORDED"
    assert evidence["data_latency_ms"] == 123
    assert evidence["schema_version"] == "2"

    rows = runtime._read_signals(limit=10)
    assert len(rows) == 1
    row = rows[0]
    assert row["signal_id"] == evidence["signal_id"]
    assert row["reason_codes"] == ["market_baseline", "fresh_market_quote"]
    assert verify_signal(row)
    assert verify_merkle_proof(
        row["record_sha256"],
        row["merkle_proof"],
        row["merkle_root"],
    )


def test_evidence_routes_registered_on_deployment_app():
    from main import app

    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/v1/evidence/signals" in paths
    assert "/v1/evidence/signals/{signal_id}" in paths
    assert "/v1/evidence/verify/{signal_id}" in paths
    assert "/v1/evidence/roots/{date}" in paths
