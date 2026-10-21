from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.metadata
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import requests

SPORTS = ("NFL", "NBA", "MLB", "NHL")
MAX_DAILY_RANGE = 31


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def _records(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    if hasattr(frame, "to_dicts"):
        return list(frame.to_dicts())
    if hasattr(frame, "to_dict"):
        try:
            return list(frame.to_dict(orient="records"))
        except TypeError:
            pass
    if isinstance(frame, list):
        return [item for item in frame if isinstance(item, dict)]
    return []


def _write(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _canonical(payload)
    compressed = gzip.compress(raw, compresslevel=9)
    path.write_bytes(compressed)
    return {
        "path": str(path),
        "sha256": hashlib.sha256(compressed).hexdigest(),
        "uncompressed_sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(compressed),
    }


def _bounded_dates(start: str, end: str) -> list[date]:
    first = date.fromisoformat(start)
    last = date.fromisoformat(end)
    if last < first:
        raise ValueError("end-date must not precede start-date")
    days = (last - first).days + 1
    if days > MAX_DAILY_RANGE:
        raise ValueError(f"date range is limited to {MAX_DAILY_RANGE} days per acquisition artifact")
    return [first + timedelta(days=offset) for offset in range(days)]


def _safe_optional(loader: Callable[..., Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        return {"status": "OK", "rows": _records(loader(*args, **kwargs))}
    except Exception as exc:
        return {"status": "UNAVAILABLE", "error_type": type(exc).__name__, "rows": []}


def collect_nfl(season: int, rich: bool) -> dict[str, Any]:
    import nflreadpy as nfl

    payload: dict[str, Any] = {
        "schedules": _safe_optional(nfl.load_schedules, [season]),
        "team_stats": _safe_optional(nfl.load_team_stats, [season], summary_level="week"),
        "player_stats": _safe_optional(nfl.load_player_stats, [season], summary_level="week"),
        "injuries": _safe_optional(nfl.load_injuries, [season]),
        "weekly_rosters": _safe_optional(nfl.load_rosters_weekly, [season]),
        "depth_charts": _safe_optional(nfl.load_depth_charts, [season]),
        "source": "nflverse/nflreadpy",
        "season": season,
    }
    if rich:
        payload.update(
            {
                "snap_counts": _safe_optional(nfl.load_snap_counts, [season]),
                "participation": _safe_optional(nfl.load_participation, [season]),
                "play_by_play": _safe_optional(nfl.load_pbp, [season]),
                "nextgen_passing": _safe_optional(nfl.load_nextgen_stats, [season], stat_type="passing"),
                "nextgen_receiving": _safe_optional(nfl.load_nextgen_stats, [season], stat_type="receiving"),
                "nextgen_rushing": _safe_optional(nfl.load_nextgen_stats, [season], stat_type="rushing"),
            }
        )
    return payload


def collect_nba(season: str) -> dict[str, Any]:
    from nba_api.stats.endpoints import leaguegamelog, playergamelogs

    team = leaguegamelog.LeagueGameLog(
        season=season,
        player_or_team_abbreviation="T",
        timeout=60,
    ).get_data_frames()
    try:
        players = playergamelogs.PlayerGameLogs(
            season_nullable=season,
            season_type_nullable="Regular Season",
            timeout=60,
        ).get_data_frames()
    except Exception:
        # LeagueGameLog player mode is a documented fallback if PlayerGameLogs
        # is unavailable from the current network/library release.
        players = leaguegamelog.LeagueGameLog(
            season=season,
            player_or_team_abbreviation="P",
            timeout=60,
        ).get_data_frames()
    return {
        "team_game_logs": _records(team[0] if team else None),
        "player_game_logs": _records(players[0] if players else None),
        "source": "swar/nba_api",
        "season": season,
    }


def collect_mlb(start_date: str, end_date: str, rich: bool) -> dict[str, Any]:
    dates = _bounded_dates(start_date, end_date)
    schedules: list[dict[str, Any]] = []
    for day in dates:
        response = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule",
            params={"sportId": 1, "date": day.isoformat(), "hydrate": "probablePitcher,venue"},
            headers={"Accept": "application/json", "User-Agent": "PhilthySports-Historical/1.0"},
            timeout=(5, 30),
            allow_redirects=False,
        )
        response.raise_for_status()
        schedules.append({"date": day.isoformat(), "payload": response.json()})
    payload: dict[str, Any] = {
        "schedules": schedules,
        "source": "MLB StatsAPI",
        "start_date": start_date,
        "end_date": end_date,
    }
    if rich:
        try:
            from pybaseball import statcast

            statcast_frame = statcast(start_dt=start_date, end_dt=end_date, verbose=False)
            payload["statcast"] = {"status": "OK", "rows": _records(statcast_frame)}
            payload["statcast_source"] = "pybaseball/Baseball Savant"
        except Exception as exc:
            payload["statcast"] = {"status": "UNAVAILABLE", "error_type": type(exc).__name__, "rows": []}
    return payload


def collect_nhl(start_date: str, end_date: str, rich: bool) -> dict[str, Any]:
    dates = _bounded_dates(start_date, end_date)
    schedules: list[dict[str, Any]] = []
    boxscores: list[dict[str, Any]] = []
    seen_games: set[str] = set()
    session = requests.Session()
    session.headers.update({"Accept": "application/json", "User-Agent": "PhilthySports-Historical/1.0"})
    for day in dates:
        url = f"https://api-web.nhle.com/v1/schedule/{day.isoformat()}"
        response = session.get(url, timeout=(5, 30), allow_redirects=False)
        response.raise_for_status()
        data = response.json()
        schedules.append({"date": day.isoformat(), "payload": data})
        if not rich:
            continue
        for game_day in data.get("gameWeek") or []:
            for game in game_day.get("games") or []:
                game_id = str(game.get("id") or "")
                if not game_id or game_id in seen_games:
                    continue
                seen_games.add(game_id)
                detail = session.get(
                    f"https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore",
                    timeout=(5, 30),
                    allow_redirects=False,
                )
                if detail.status_code == 200:
                    boxscores.append({"game_id": game_id, "payload": detail.json()})
                detail.close()
        response.close()
    return {
        "schedules": schedules,
        "boxscores": boxscores,
        "source": "NHL Web API",
        "start_date": start_date,
        "end_date": end_date,
    }


def package_versions() -> dict[str, str | None]:
    names = ["nflreadpy", "nba_api", "pybaseball", "requests"]
    versions: dict[str, str | None] = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def collect(
    sport: str,
    output_dir: Path,
    *,
    season: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    rich: bool = False,
) -> dict[str, Any]:
    sport = sport.upper().strip()
    if sport not in SPORTS:
        raise ValueError("unsupported sport")
    if sport == "NFL":
        if not season:
            raise ValueError("season is required for NFL")
        payload = collect_nfl(int(season), rich)
        scope = season
    elif sport == "NBA":
        if not season:
            raise ValueError("season is required for NBA")
        payload = collect_nba(season)
        scope = season
    elif sport == "MLB":
        if not start_date or not end_date:
            raise ValueError("start_date and end_date are required for MLB")
        payload = collect_mlb(start_date, end_date, rich)
        scope = f"{start_date}_{end_date}"
    else:
        if not start_date or not end_date:
            raise ValueError("start_date and end_date are required for NHL")
        payload = collect_nhl(start_date, end_date, rich)
        scope = f"{start_date}_{end_date}"

    retrieved_at = datetime.now(timezone.utc).isoformat()
    artifact_doc = {
        "sport": sport,
        "scope": scope,
        "retrieved_at": retrieved_at,
        "rich": bool(rich),
        "payload": payload,
        "authority": {
            "trusted_for_instructions": False,
            "historical_training_eligible": False,
            "promotion_eligible": False,
            "canonical_admission_required": True,
        },
    }
    safe_scope = scope.replace("/", "-").replace(" ", "_")
    artifact = _write(output_dir / f"{sport.lower()}_features_{safe_scope}.json.gz", artifact_doc)
    manifest = {
        "schema_version": "historical-feature-source-v1",
        "sport": sport,
        "scope": scope,
        "retrieved_at": retrieved_at,
        "artifact": artifact,
        "package_versions": package_versions(),
        "purpose": "historical feature acquisition for later point-in-time canonicalization",
        "promotion_eligible": False,
        "canonical_admission_required": True,
        "warning": (
            "Historical values are not automatically pregame-known. Feature engineering must establish an observed_at "
            "timestamp no later than each prediction snapshot before admission."
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / f"{sport.lower()}_features_{safe_scope}_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Acquire rich historical feature evidence for canonicalization")
    parser.add_argument("--sport", required=True, choices=list(SPORTS))
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--season")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--rich", action="store_true")
    args = parser.parse_args()
    print(json.dumps(collect(
        args.sport,
        args.output_dir,
        season=args.season,
        start_date=args.start_date,
        end_date=args.end_date,
        rich=args.rich,
    ), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
