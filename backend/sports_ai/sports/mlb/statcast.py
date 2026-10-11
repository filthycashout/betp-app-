from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import mean
from typing import Any, Iterable

import requests

SAVANT_BASE = "https://baseballsavant.mlb.com/statcast_search/csv"


def _utc(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _float(value: Any) -> float | None:
    if value in (None, "", "null", "None", "nan", "NaN"):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def _date(value: Any) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _rows_before_target(rows: Iterable[dict[str, Any]], target_event_time: str) -> list[dict[str, Any]]:
    target = _utc(target_event_time)
    if target is None:
        raise ValueError("target_event_time must be a valid timestamp")
    # Statcast CSV game_date is a date, not a full pitch timestamp. Excluding the
    # entire target date is conservative and prevents same-day doubleheader or
    # delayed-game leakage into a pregame feature snapshot.
    cutoff = target.date()
    return [row for row in rows if (_date(row.get("game_date")) is not None and _date(row.get("game_date")) < cutoff)]


def summarize_batter_statcast(rows: Iterable[dict[str, Any]], target_event_time: str) -> dict[str, Any]:
    accepted = _rows_before_target(rows, target_event_time)
    xwoba = [value for row in accepted if (value := _float(row.get("estimated_woba_using_speedangle"))) is not None]
    exit_velocities = [value for row in accepted if (value := _float(row.get("launch_speed"))) is not None]
    launch_angles = [value for row in accepted if (value := _float(row.get("launch_angle"))) is not None]
    bbe = [row for row in accepted if _float(row.get("launch_speed")) is not None and _float(row.get("launch_angle")) is not None]
    barrels = sum(1 for row in bbe if _float(row.get("launch_speed_angle")) == 6.0)
    event_rows = [row for row in accepted if str(row.get("events") or "").strip()]
    game_pks = sorted({str(row.get("game_pk")) for row in accepted if str(row.get("game_pk") or "").strip()})
    return {
        "pitch_rows": len(accepted),
        "plate_appearance_events": len(event_rows),
        "batted_ball_events": len(bbe),
        "games": len(game_pks),
        "game_pks": game_pks,
        "xwoba_on_contact": round(mean(xwoba), 4) if xwoba else None,
        "average_exit_velocity": round(mean(exit_velocities), 2) if exit_velocities else None,
        "average_launch_angle": round(mean(launch_angles), 2) if launch_angles else None,
        "barrel_rate": round(barrels / len(bbe), 4) if bbe else None,
        "barrels": barrels,
        "source_fields": [
            "estimated_woba_using_speedangle",
            "launch_speed",
            "launch_angle",
            "launch_speed_angle",
        ],
    }


def summarize_pitcher_statcast(rows: Iterable[dict[str, Any]], target_event_time: str) -> dict[str, Any]:
    accepted = _rows_before_target(rows, target_event_time)
    pitch_rows = [row for row in accepted if str(row.get("pitch_type") or "").strip()]
    counts = Counter(str(row.get("pitch_type")) for row in pitch_rows)
    velocities: dict[str, list[float]] = defaultdict(list)
    for row in pitch_rows:
        pitch_type = str(row.get("pitch_type"))
        velocity = _float(row.get("release_speed"))
        if velocity is not None:
            velocities[pitch_type].append(velocity)
    xwoba_allowed = [value for row in accepted if (value := _float(row.get("estimated_woba_using_speedangle"))) is not None]
    total = len(pitch_rows)
    pitch_mix = [
        {
            "pitch_type": pitch_type,
            "pitches": count,
            "share": round(count / total, 4) if total else None,
            "average_velocity": round(mean(velocities[pitch_type]), 2) if velocities[pitch_type] else None,
        }
        for pitch_type, count in counts.most_common()
    ]
    game_pks = sorted({str(row.get("game_pk")) for row in accepted if str(row.get("game_pk") or "").strip()})
    return {
        "pitch_rows": len(accepted),
        "classified_pitches": total,
        "games": len(game_pks),
        "game_pks": game_pks,
        "xwoba_allowed_on_contact": round(mean(xwoba_allowed), 4) if xwoba_allowed else None,
        "pitch_mix": pitch_mix,
        "source_fields": [
            "pitch_type",
            "release_speed",
            "estimated_woba_using_speedangle",
        ],
    }


def _query_url(*, player_type: str, player_id: int, start_date: str, end_date: str) -> str:
    lookup = "batters_lookup%5B%5D" if player_type == "batter" else "pitchers_lookup%5B%5D"
    return (
        f"{SAVANT_BASE}?all=true&hfPT=&hfAB=&hfBBT=&hfPR=&hfZ=&stadium=&hfBBL=&hfNewZones="
        f"&hfGT=R%7CPO%7CS%7C=&hfSea=&hfSit=&player_type={player_type}&hfOuts=&opponent="
        f"&pitcher_throws=&batter_stands=&hfSA=&game_date_gt={start_date}&game_date_lt={end_date}"
        f"&{lookup}={int(player_id)}&team=&position=&hfRO=&home_road=&hfFlag=&metric_1=&hfInn="
        "&min_pitches=0&min_results=0&group_by=name&sort_col=pitches&player_event_sort=h_launch_speed"
        "&sort_order=desc&min_abs=0&type=details&"
    )


def fetch_player_statcast_rows(
    player_id: int,
    *,
    player_type: str,
    target_event_time: str,
    lookback_days: int = 30,
    session: requests.Session | None = None,
) -> list[dict[str, str]]:
    """Fetch a bounded, chronology-safe Baseball Savant CSV window.

    The query shape mirrors the current pybaseball statcast_batter/statcast_pitcher
    wrappers, but parsing uses the standard library so this backend does not need
    pandas merely to create pregame context.
    """

    if player_type not in {"batter", "pitcher"}:
        raise ValueError("player_type must be batter or pitcher")
    target = _utc(target_event_time)
    if target is None:
        raise ValueError("target_event_time must be a valid timestamp")
    end = target.date() - timedelta(days=1)
    start = end - timedelta(days=max(1, int(lookback_days)) - 1)
    client = session or requests.Session()
    response = client.get(
        _query_url(
            player_type=player_type,
            player_id=int(player_id),
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        ),
        headers={"Accept": "text/csv", "User-Agent": "PhilthyParleys/StatcastContext"},
        timeout=(3, 30),
    )
    response.raise_for_status()
    text = response.text
    if not text.strip():
        return []
    return [dict(row) for row in csv.DictReader(io.StringIO(text))]


def fetch_batter_statcast_context(
    player_id: int,
    *,
    target_event_time: str,
    lookback_days: int = 30,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    rows = fetch_player_statcast_rows(
        player_id,
        player_type="batter",
        target_event_time=target_event_time,
        lookback_days=lookback_days,
        session=session,
    )
    return {
        "player_id": int(player_id),
        "player_type": "batter",
        "lookback_days": lookback_days,
        "point_in_time_rule": "Statcast game_date must be strictly before target game date",
        "source": "baseball_savant_statcast_csv",
        "model_influence": False,
        **summarize_batter_statcast(rows, target_event_time),
    }


def fetch_pitcher_statcast_context(
    player_id: int,
    *,
    target_event_time: str,
    lookback_days: int = 30,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    rows = fetch_player_statcast_rows(
        player_id,
        player_type="pitcher",
        target_event_time=target_event_time,
        lookback_days=lookback_days,
        session=session,
    )
    return {
        "player_id": int(player_id),
        "player_type": "pitcher",
        "lookback_days": lookback_days,
        "point_in_time_rule": "Statcast game_date must be strictly before target game date",
        "source": "baseball_savant_statcast_csv",
        "model_influence": False,
        **summarize_pitcher_statcast(rows, target_event_time),
    }
