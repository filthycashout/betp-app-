from __future__ import annotations

import pandas as pd

from training.point_in_time_features import build_point_in_time_features


def base_rows():
    return [
        {
            "sport": "NBA",
            "event_id": "g1",
            "event_time": "2026-10-01T02:00:00Z",
            "snapshot_time": "2026-10-01T00:00:00Z",
            "settled_time": "2026-10-01T05:00:00Z",
            "target": 1,
            "market_prob": 0.55,
            "consensus_de_vig_home_probability": 0.54,
            "home_spread": 0.0,
            "consensus_total": 220.0,
            "home_team": "A",
            "away_team": "B",
            "home_score": 110,
            "away_score": 100,
        },
        {
            "sport": "NBA",
            "event_id": "g2",
            "event_time": "2026-10-03T02:00:00Z",
            "snapshot_time": "2026-10-03T00:00:00Z",
            "settled_time": "2026-10-03T05:00:00Z",
            "target": 0,
            "market_prob": 0.48,
            "consensus_de_vig_home_probability": 0.49,
            "home_spread": 1.5,
            "consensus_total": 218.5,
            "home_team": "C",
            "away_team": "A",
            "home_score": 101,
            "away_score": 108,
        },
        {
            "sport": "NBA",
            "event_id": "g3",
            "event_time": "2026-10-05T02:00:00Z",
            "snapshot_time": "2026-10-05T00:00:00Z",
            "settled_time": "2026-10-05T05:00:00Z",
            "target": 1,
            "market_prob": 0.58,
            "consensus_de_vig_home_probability": 0.57,
            "home_spread": -3.0,
            "consensus_total": 221.0,
            "home_team": "A",
            "away_team": "D",
            "home_score": 115,
            "away_score": 109,
        },
    ]


def test_features_use_only_already_settled_prior_games():
    result = build_point_in_time_features(pd.DataFrame(base_rows()))
    g1 = result[result["event_id"] == "g1"].iloc[0]
    g2 = result[result["event_id"] == "g2"].iloc[0]
    g3 = result[result["event_id"] == "g3"].iloc[0]
    assert g1["feature_home_games_prior"] == 0
    assert g2["feature_away_games_prior"] == 1
    assert g2["feature_away_win_pct_last5"] == 1.0
    # A won g1 and g2 (as away team) before the g3 snapshot.
    assert g3["feature_home_games_prior"] == 2
    assert g3["feature_home_win_pct_last5"] == 1.0
    assert g3["feature_home_point_diff_last5"] == 8.5


def test_unsettled_prior_outcome_is_not_available_to_next_snapshot():
    rows = base_rows()
    rows[0]["settled_time"] = "2026-10-04T05:00:00Z"
    result = build_point_in_time_features(pd.DataFrame(rows))
    g2 = result[result["event_id"] == "g2"].iloc[0]
    assert g2["feature_away_games_prior"] == 0


def test_zero_spread_is_preserved_as_numeric_feature():
    result = build_point_in_time_features(pd.DataFrame(base_rows()))
    g1 = result[result["event_id"] == "g1"].iloc[0]
    assert g1["feature_home_spread"] == 0.0


def test_every_generated_feature_is_observed_at_snapshot():
    result = build_point_in_time_features(pd.DataFrame(base_rows()))
    feature_columns = [c for c in result.columns if c.startswith("feature_") and not c.endswith("_observed_at")]
    for feature in feature_columns:
        observed = f"{feature}_observed_at"
        assert observed in result.columns
        assert (result[observed] == result["snapshot_time"]).all()
