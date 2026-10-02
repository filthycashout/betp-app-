from __future__ import annotations

import argparse
import csv
import hashlib
import json
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SPORTS = ("NFL", "NBA", "MLB", "NHL")
ESPN = {
    "NFL": ("football", "nfl"),
    "NBA": ("basketball", "nba"),
}


def _json(url: str, timeout: int = 45) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "PhilthySports-v8-evidence/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def capture(base_url: str, output_dir: Path, days: int = 4) -> None:
    fetched_at = datetime.now(timezone.utc)
    query = urllib.parse.urlencode(
        {"include_props": "true", "props_limit": "20", "days": str(days)}
    )
    source_url = f"{base_url.rstrip('/')}/v1/today?{query}"
    payload = _json(source_url)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = fetched_at.strftime("%Y%m%dT%H%M%SZ")

    raw_path = output_dir / f"powerhouse_raw_{stamp}.json"
    raw_doc = {
        "fetched_at": fetched_at.isoformat(),
        "source_url": source_url,
        "payload": payload,
    }
    raw_path.write_bytes(_canonical(raw_doc))

    rows = []
    for game in payload.get("games") or []:
        event_time = game.get("event_time")
        if not event_time:
            continue
        try:
            event_dt = _parse_time(str(event_time))
        except Exception:
            continue
        if fetched_at >= event_dt:
            continue

        market = game.get("market") or {}
        row = {
            "sport": str(game.get("sport") or "").upper(),
            "event_id": str(game.get("event_id") or ""),
            "event_time": event_dt.isoformat(),
            "as_of": fetched_at.isoformat(),
            "home_team": game.get("home"),
            "away_team": game.get("away"),
            "market_home_probability": market.get("home_probability"),
            "consensus_de_vig_home_probability": market.get("home_probability"),
            "home_spread": market.get("home_spread"),
            "consensus_total": market.get("total"),
            "probability_source": game.get("probability_source"),
            "model_status": game.get("model_status"),
            "schedule_source": game.get("schedule_source"),
            "injury_home_count": (
                ((game.get("injury_report") or {}).get("home") or {}).get("count")
            ),
            "injury_away_count": (
                ((game.get("injury_report") or {}).get("away") or {}).get("count")
            ),
            "props": game.get("props_to_watch") or [],
        }
        if row["sport"] in SPORTS and row["event_id"]:
            rows.append(row)

    rows.sort(key=lambda x: (x["sport"], x["event_time"], x["event_id"]))
    rows_path = output_dir / f"pregame_{stamp}.jsonl"
    with rows_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")

    manifest = {
        "schema_version": 1,
        "capture_type": "strict_pregame",
        "fetched_at": fetched_at.isoformat(),
        "source_url": source_url,
        "raw_file": {
            "name": raw_path.name,
            "sha256": _sha256(raw_path),
            "bytes": raw_path.stat().st_size,
        },
        "rows_file": {
            "name": rows_path.name,
            "sha256": _sha256(rows_path),
            "bytes": rows_path.stat().st_size,
            "rows": len(rows),
        },
        "chronology_rule": "as_of < event_time",
        "secrets_embedded": False,
    }
    manifest_path = output_dir / f"manifest_{stamp}.json"
    manifest_path.write_bytes(_canonical(manifest))
    print(json.dumps(manifest, indent=2, sort_keys=True))


def _espn_results(sport: str, game_date: date) -> dict[str, int]:
    category, league = ESPN[sport]
    ymd = game_date.strftime("%Y%m%d")
    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/"
        f"{category}/{league}/scoreboard?dates={ymd}"
    )
    raw = _json(url)
    out = {}
    for event in raw.get("events") or []:
        competition = ((event.get("competitions") or [{}])[0]) or {}
        status = (event.get("status") or {}).get("type") or {}
        if not bool(status.get("completed")):
            continue
        competitors = competition.get("competitors") or []
        home = next((x for x in competitors if x.get("homeAway") == "home"), None)
        away = next((x for x in competitors if x.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        try:
            home_score = float(home.get("score"))
            away_score = float(away.get("score"))
        except (TypeError, ValueError):
            continue
        if home_score == away_score:
            continue
        out[str(event.get("id"))] = int(home_score > away_score)
    return out


def _mlb_results(game_date: date) -> dict[str, int]:
    params = urllib.parse.urlencode({"sportId": 1, "date": game_date.isoformat()})
    raw = _json(f"https://statsapi.mlb.com/api/v1/schedule?{params}")
    out = {}
    for day in raw.get("dates") or []:
        for game in day.get("games") or []:
            status = game.get("status") or {}
            if status.get("abstractGameState") != "Final":
                continue
            home = ((game.get("teams") or {}).get("home") or {})
            away = ((game.get("teams") or {}).get("away") or {})
            try:
                hs = float(home.get("score"))
                as_ = float(away.get("score"))
            except (TypeError, ValueError):
                continue
            if hs == as_:
                continue
            out[str(game.get("gamePk"))] = int(hs > as_)
    return out


def _nhl_results(game_date: date) -> dict[str, int]:
    raw = _json(f"https://api-web.nhle.com/v1/schedule/{game_date.isoformat()}")
    out = {}
    for day in raw.get("gameWeek") or []:
        if day.get("date") != game_date.isoformat():
            continue
        for game in day.get("games") or []:
            if str(game.get("gameState") or "").upper() not in {"OFF", "FINAL"}:
                continue
            home = game.get("homeTeam") or {}
            away = game.get("awayTeam") or {}
            try:
                hs = float(home.get("score"))
                as_ = float(away.get("score"))
            except (TypeError, ValueError):
                continue
            if hs == as_:
                continue
            out[str(game.get("id"))] = int(hs > as_)
    return out


def _all_pregame_rows(root: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted((root / "pregame").rglob("pregame_*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    row = json.loads(line)
                    row["_source_path"] = str(path.relative_to(root))
                    rows.append(row)
    return rows


def settle(root: Path, lookback_days: int = 14) -> None:
    rows = _all_pregame_rows(root)
    today = datetime.now(timezone.utc).date()
    labels: dict[tuple[str, str], dict[str, Any]] = {}
    requested: dict[tuple[str, date], set[str]] = {}

    for row in rows:
        try:
            game_date = _parse_time(row["event_time"]).date()
        except Exception:
            continue
        if game_date > today or game_date < today - timedelta(days=lookback_days):
            continue
        key = (row["sport"], game_date)
        requested.setdefault(key, set()).add(row["event_id"])

    cache: dict[tuple[str, date], dict[str, int]] = {}
    for key in sorted(requested, key=lambda x: (x[1], x[0])):
        sport, game_date = key
        try:
            if sport in ESPN:
                cache[key] = _espn_results(sport, game_date)
            elif sport == "MLB":
                cache[key] = _mlb_results(game_date)
            elif sport == "NHL":
                cache[key] = _nhl_results(game_date)
        except Exception:
            cache[key] = {}

    for row in rows:
        try:
            game_date = _parse_time(row["event_time"]).date()
        except Exception:
            continue
        result = cache.get((row["sport"], game_date), {}).get(row["event_id"])
        if result is None:
            continue
        labels[(row["sport"], row["event_id"])] = {
            "sport": row["sport"],
            "event_id": row["event_id"],
            "event_date": game_date.isoformat(),
            "target_home_win": result,
            "settled_at": datetime.now(timezone.utc).isoformat(),
            "result_source": (
                "ESPN scoreboard"
                if row["sport"] in ESPN
                else "MLB Stats API"
                if row["sport"] == "MLB"
                else "NHL Web API"
            ),
        }

    settled_dir = root / "settled"
    settled_dir.mkdir(parents=True, exist_ok=True)
    labels_path = settled_dir / "labels.jsonl"
    with labels_path.open("w", encoding="utf-8") as handle:
        for item in sorted(labels.values(), key=lambda x: (x["sport"], x["event_date"], x["event_id"])):
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    print(json.dumps({"settled_labels": len(labels), "sha256": _sha256(labels_path)}, indent=2))


def build(root: Path) -> None:
    rows = _all_pregame_rows(root)
    labels_path = root / "settled" / "labels.jsonl"
    labels: dict[tuple[str, str], dict[str, Any]] = {}
    if labels_path.exists():
        with labels_path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    item = json.loads(line)
                    labels[(item["sport"], item["event_id"])] = item

    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["sport"], row["event_id"])
        existing = latest.get(key)
        if existing is None or row["as_of"] > existing["as_of"]:
            latest[key] = row

    canonical_dir = root / "canonical"
    canonical_dir.mkdir(parents=True, exist_ok=True)
    columns = [
        "sport",
        "event_id",
        "event_time",
        "as_of",
        "home_team",
        "away_team",
        "target_home_win",
        "market_home_probability",
        "consensus_de_vig_home_probability",
        "home_spread",
        "consensus_total",
    ]
    source_files = sorted(str(p.relative_to(root)) for p in (root / "pregame").rglob("pregame_*.jsonl"))

    for sport in SPORTS:
        merged = []
        for (row_sport, event_id), row in latest.items():
            if row_sport != sport:
                continue
            label = labels.get((sport, event_id))
            if label is None:
                continue
            try:
                if _parse_time(row["as_of"]) >= _parse_time(row["event_time"]):
                    continue
            except Exception:
                continue
            merged.append({
                "sport": sport,
                "event_id": event_id,
                "event_time": row["event_time"],
                "as_of": row["as_of"],
                "home_team": row.get("home_team"),
                "away_team": row.get("away_team"),
                "target_home_win": label["target_home_win"],
                "market_home_probability": row.get("market_home_probability"),
                "consensus_de_vig_home_probability": row.get("consensus_de_vig_home_probability"),
                "home_spread": row.get("home_spread"),
                "consensus_total": row.get("consensus_total"),
            })
        merged.sort(key=lambda x: (x["event_time"], x["event_id"]))

        csv_path = canonical_dir / f"{sport.lower()}.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(merged)

        schema = {
            "schema_version": 1,
            "columns": columns,
            "runtime_features": [
                "consensus_de_vig_home_probability",
                "home_spread",
                "consensus_total",
            ],
            "target": "target_home_win",
            "chronology": "as_of < event_time",
        }
        manifest = {
            "sport": sport,
            "rows": len(merged),
            "canonical_file": csv_path.name,
            "canonical_sha256": _sha256(csv_path),
            "schema": schema,
            "schema_sha256": hashlib.sha256(_canonical(schema)).hexdigest(),
            "labels_sha256": _sha256(labels_path) if labels_path.exists() else None,
            "pregame_sources": source_files,
            "pregame_source_manifest_sha256": hashlib.sha256(
                _canonical(source_files)
            ).hexdigest(),
            "promotion_ready": False,
            "promotion_ready_reason": (
                "Canonical evidence is accumulated automatically, but strict v8 "
                "sample, OOF calibration, metric, leakage, and artifact gates must "
                "still be executed before promotion."
            ),
        }
        manifest_path = canonical_dir / f"{sport.lower()}_source_manifest.json"
        manifest_path.write_bytes(_canonical(manifest))

    print(json.dumps({"canonical_dir": str(canonical_dir)}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    capture_p = sub.add_parser("capture")
    capture_p.add_argument("--base-url", default="https://philthysports-powerhouse-v8.onrender.com")
    capture_p.add_argument("--output-dir", required=True, type=Path)
    capture_p.add_argument("--days", type=int, default=4)

    settle_p = sub.add_parser("settle")
    settle_p.add_argument("--root", required=True, type=Path)
    settle_p.add_argument("--lookback-days", type=int, default=14)

    build_p = sub.add_parser("build")
    build_p.add_argument("--root", required=True, type=Path)

    args = parser.parse_args()
    if args.command == "capture":
        capture(args.base_url, args.output_dir, args.days)
    elif args.command == "settle":
        settle(args.root, args.lookback_days)
    else:
        build(args.root)


if __name__ == "__main__":
    main()
