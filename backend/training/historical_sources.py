from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.metadata
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _write_json_gz(path: Path, value: Any) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _canonical(value)
    payload = gzip.compress(raw, compresslevel=9)
    path.write_bytes(payload)
    return {
        "path": str(path),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "uncompressed_sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(payload),
    }


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
        return [x for x in frame if isinstance(x, dict)]
    return []


def collect_nfl(season: int) -> dict[str, Any]:
    import nflreadpy as nfl

    return {
        "schedules": _records(nfl.load_schedules([season])),
        "team_stats": _records(nfl.load_team_stats([season])),
        "injuries": _records(nfl.load_injuries([season])),
        "source": "nflverse/nflreadpy",
        "season": season,
    }


def collect_nba(season: str) -> dict[str, Any]:
    from nba_api.stats.endpoints import leaguegamelog

    endpoint = leaguegamelog.LeagueGameLog(
        season=season,
        player_or_team_abbreviation="T",
        timeout=60,
    )
    frames = endpoint.get_data_frames()
    return {
        "team_game_logs": _records(frames[0] if frames else None),
        "source": "swar/nba_api",
        "season": season,
    }


def _dates(start_date: str, end_date: str):
    current = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    while current <= end:
        yield current
        current += timedelta(days=1)


def collect_mlb(start_date: str, end_date: str) -> dict[str, Any]:
    from mlbstatsapi import Mlb

    schedules: list[dict[str, Any]] = []
    with Mlb() as mlb:
        for d in _dates(start_date, end_date):
            rows = mlb.get_schedule(date=d.isoformat())
            if hasattr(rows, "model_dump"):
                rows = rows.model_dump(exclude_none=True)
            schedules.append({"date": d.isoformat(), "payload": rows})
    return {
        "schedules": schedules,
        "source": "zero-sum-seattle/python-mlb-statsapi",
        "start_date": start_date,
        "end_date": end_date,
        "feature_research_source": "jldbc/pybaseball",
    }


def collect_nhl(start_date: str, end_date: str) -> dict[str, Any]:
    from nhlpy import NHLClient

    client = NHLClient(timeout=30)
    schedules = []
    for d in _dates(start_date, end_date):
        schedules.append({
            "date": d.isoformat(),
            "payload": client.schedule.daily_schedule(date=d.isoformat()),
        })
    return {
        "schedules": schedules,
        "source": "coreyjs/nhl-api-py",
        "start_date": start_date,
        "end_date": end_date,
    }


def package_versions() -> dict[str, str | None]:
    names = [
        "nflreadpy",
        "nba_api",
        "python-mlb-statsapi",
        "pybaseball",
        "nhl-api-py",
    ]
    versions = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch public historical source evidence without executing legacy joblibs."
    )
    parser.add_argument("--sport", required=True, choices=["NFL", "NBA", "MLB", "NHL"])
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--season", help="NFL year (2025) or NBA season (2025-26)")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    args = parser.parse_args()

    if args.sport == "NFL":
        if not args.season:
            raise SystemExit("--season is required for NFL")
        payload = collect_nfl(int(args.season))
    elif args.sport == "NBA":
        if not args.season:
            raise SystemExit("--season is required for NBA")
        payload = collect_nba(args.season)
    elif args.sport == "MLB":
        if not args.start_date or not args.end_date:
            raise SystemExit("--start-date and --end-date are required for MLB")
        payload = collect_mlb(args.start_date, args.end_date)
    else:
        if not args.start_date or not args.end_date:
            raise SystemExit("--start-date and --end-date are required for NHL")
        payload = collect_nhl(args.start_date, args.end_date)

    versions = package_versions()
    artifact = _write_json_gz(
        args.output_dir / f"{args.sport.lower()}_public_source.json.gz",
        payload,
    )
    manifest = {
        "sport": args.sport,
        "artifact": artifact,
        "package_versions": versions,
        "provenance": {
            "credential_source": "none",
            "legacy_serialized_models_executed": False,
            "purpose": "historical source acquisition for later canonicalization",
        },
    }
    manifest_path = args.output_dir / f"{args.sport.lower()}_source_manifest.json"
    manifest_path.write_bytes(_canonical(manifest))
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
