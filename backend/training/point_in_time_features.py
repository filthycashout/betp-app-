from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from training.sports_omni_contract import normalize_drive_frame

WINDOWS = (5, 10)


@dataclass(frozen=True)
class TeamGame:
    event_time: pd.Timestamp
    settled_time: pd.Timestamp
    won: float
    points_for: float | None
    points_against: float | None


def _optional_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _number_or_nan(value: Any) -> float:
    number = _optional_number(value)
    return np.nan if number is None else number


def _team_history_before(
    frame: pd.DataFrame,
    row_index: int,
    team: str,
    snapshot: pd.Timestamp,
) -> list[TeamGame]:
    history: list[TeamGame] = []
    for idx, prior in frame.iterrows():
        if idx == row_index:
            continue
        settled = prior["_settled_time"]
        if settled >= snapshot:
            continue
        event_time = prior["_event_time"]
        if event_time >= snapshot:
            continue
        home = str(prior["home_team"])
        away = str(prior["away_team"])
        if team not in {home, away}:
            continue
        target = float(prior["target"])
        won = target if team == home else 1.0 - target
        home_score = _optional_number(prior.get("home_score"))
        away_score = _optional_number(prior.get("away_score"))
        points_for: float | None = None
        points_against: float | None = None
        if home_score is not None and away_score is not None:
            if team == home:
                points_for, points_against = home_score, away_score
            else:
                points_for, points_against = away_score, home_score
        history.append(
            TeamGame(
                event_time=event_time,
                settled_time=settled,
                won=won,
                points_for=points_for,
                points_against=points_against,
            )
        )
    history.sort(key=lambda item: item.event_time)
    return history


def _streak(history: list[TeamGame]) -> float:
    if not history:
        return 0.0
    last = history[-1].won
    count = 0
    for item in reversed(history):
        if item.won != last:
            break
        count += 1
    return float(count if last == 1.0 else -count)


def _features_for_team(history: list[TeamGame], snapshot: pd.Timestamp) -> dict[str, float]:
    features: dict[str, float] = {
        "games_prior": float(len(history)),
        "streak": _streak(history),
    }
    if history:
        rest = (snapshot - history[-1].event_time).total_seconds() / 86400.0
        features["rest_days"] = float(max(0.0, min(rest, 30.0)))
    else:
        features["rest_days"] = np.nan
    for window in WINDOWS:
        sample = history[-window:]
        suffix = f"last{window}"
        if sample:
            features[f"win_pct_{suffix}"] = float(np.mean([game.won for game in sample]))
        else:
            features[f"win_pct_{suffix}"] = np.nan
        scored = [game.points_for for game in sample if game.points_for is not None]
        allowed = [game.points_against for game in sample if game.points_against is not None]
        diffs = [
            game.points_for - game.points_against
            for game in sample
            if game.points_for is not None and game.points_against is not None
        ]
        features[f"points_for_{suffix}"] = float(np.mean(scored)) if scored else np.nan
        features[f"points_against_{suffix}"] = float(np.mean(allowed)) if allowed else np.nan
        features[f"point_diff_{suffix}"] = float(np.mean(diffs)) if diffs else np.nan
    return features


def build_point_in_time_features(frame: pd.DataFrame) -> pd.DataFrame:
    data = normalize_drive_frame(frame)
    required_teams = {"home_team", "away_team"}
    missing = sorted(required_teams - set(data.columns))
    if missing:
        raise ValueError(f"team identity columns are required for point-in-time features: {missing}")
    data = data.copy().reset_index(drop=True)
    data["_event_time"] = pd.to_datetime(data["event_time"], utc=True, errors="raise")
    data["_snapshot_time"] = pd.to_datetime(data["snapshot_time"], utc=True, errors="raise")
    data["_settled_time"] = pd.to_datetime(data["settled_time"], utc=True, errors="raise")
    data = data.sort_values(["_event_time", "event_id"], kind="mergesort").reset_index(drop=True)

    feature_rows: list[dict[str, float]] = []
    for index, row in data.iterrows():
        snapshot = row["_snapshot_time"]
        home_history = _team_history_before(data, index, str(row["home_team"]), snapshot)
        away_history = _team_history_before(data, index, str(row["away_team"]), snapshot)
        home = _features_for_team(home_history, snapshot)
        away = _features_for_team(away_history, snapshot)
        features: dict[str, float] = {
            "feature_market_consensus_home_prob": float(row["consensus_de_vig_home_probability"]),
            "feature_market_home_prob": float(row["market_prob"]),
            "feature_home_spread": _number_or_nan(row.get("home_spread")),
            "feature_consensus_total": _number_or_nan(row.get("consensus_total")),
        }
        for name, value in home.items():
            features[f"feature_home_{name}"] = value
        for name, value in away.items():
            features[f"feature_away_{name}"] = value
        # Relative features reduce the burden on the downstream linear model and
        # remain point-in-time because each side was built from settled-only history.
        for suffix in ("games_prior", "streak", "rest_days", "win_pct_last5", "win_pct_last10", "point_diff_last5", "point_diff_last10"):
            hv = home.get(suffix, np.nan)
            av = away.get(suffix, np.nan)
            features[f"feature_delta_{suffix}"] = float(hv - av) if np.isfinite(hv) and np.isfinite(av) else np.nan
        feature_rows.append(features)

    feature_frame = pd.DataFrame(feature_rows)
    result = pd.concat([data.drop(columns=["_event_time", "_snapshot_time", "_settled_time"]), feature_frame], axis=1)
    for column in feature_frame.columns:
        result[f"{column}_observed_at"] = result["snapshot_time"]
    return result


def build_csv(source_csv: Path, output_csv: Path) -> dict[str, Any]:
    frame = pd.read_csv(source_csv)
    enriched = build_point_in_time_features(frame)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_csv(output_csv, index=False)
    return {
        "source": str(source_csv),
        "output": str(output_csv),
        "rows": len(enriched),
        "features": [c for c in enriched.columns if c.startswith("feature_") and not c.endswith("_observed_at")],
        "built_at": datetime.now(timezone.utc).isoformat(),
        "chronology_rule": "only prior events with settled_time < current snapshot_time contribute team-history features",
        "promotion_eligible": False,
    }
