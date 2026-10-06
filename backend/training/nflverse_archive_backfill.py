"""Rebuild an NFL research corpus from pinned pregame Git archive versions.

Git committer time is an archive timestamp, not a sportsbook quote timestamp or
an independently witnessed publication receipt. The report preserves that
limitation. This command never signs, promotes, or overwrites runtime models.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

COLUMNS = [
    "sport", "event_id", "event_time", "as_of", "home_team", "away_team",
    "target_home_win", "label_available_at", "market_home_probability",
    "consensus_de_vig_home_probability", "home_spread", "consensus_total",
]
MISSING = {"", "NA", "N/A", "null", "None"}
EASTERN = ZoneInfo("America/New_York")
SEASONS = {str(year) for year in range(2020, 2026)}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Archive timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def event_time(row: dict) -> datetime:
    return datetime.fromisoformat(
        row["gameday"] + "T" + row["gametime"]
    ).replace(tzinfo=EASTERN).astimezone(timezone.utc)


def number(row: dict, key: str) -> float:
    value = float(row[key])
    if not math.isfinite(value):
        raise ValueError(f"Non-finite {key}")
    return value


def implied(american: float) -> float:
    if american == 0 or not math.isfinite(american):
        raise ValueError("Invalid American moneyline")
    return -american / (100 - american) if american < 0 else 100 / (100 + american)


def score(row: dict) -> tuple[int, int] | None:
    try:
        home, away = number(row, "home_score"), number(row, "away_score")
        if min(home, away) < 0 or not home.is_integer() or not away.is_integer():
            return None
        if number(row, "result") != home - away or number(row, "total") != home + away:
            return None
        return int(home), int(away)
    except (KeyError, ValueError):
        return None


def same_event(left: dict, right: dict) -> bool:
    return all(left.get(k) == right.get(k) for k in (
        "game_id", "season", "home_team", "away_team", "gameday", "gametime"
    ))


def load_snapshots(index_path: Path, cache: Path, fetch_missing: bool) -> list[dict]:
    items = json.loads(index_path.read_text())
    snapshots = []
    seen = set()
    for item in sorted(items, key=lambda x: x["as_of"]):
        commit = item["sha"]
        if not re.fullmatch(r"[a-f0-9]{40}", commit):
            raise ValueError("Invalid upstream commit identifier")
        if commit in seen:
            continue
        seen.add(commit)
        expected_name = f"{commit}.csv"
        expected_url = f"https://raw.githubusercontent.com/nflverse/nfldata/{commit}/data/games.csv"
        if item.get("raw_file") != expected_name or item.get("url") != expected_url:
            raise ValueError("Archive path or URL differs from pinned repository")
        as_of = utc(item["as_of"])
        if as_of > utc(item["requested_at"]):
            raise ValueError("Commit is later than the historical lookup cutoff")
        path = cache / expected_name
        if not path.exists() and fetch_missing:
            cache.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(expected_url, timeout=45) as response:
                raw = response.read()
            if hashlib.sha256(raw).hexdigest() != item["raw_sha256"]:
                raise ValueError(f"Downloaded archive checksum mismatch: {commit}")
            path.write_bytes(raw)
        if digest(path) != item["raw_sha256"] or path.stat().st_size != item["raw_bytes"]:
            raise ValueError(f"Archive checksum or byte count mismatch: {commit}")
        with path.open(newline="", encoding="utf-8") as handle:
            # Hash the entire upstream file, but retain only the study seasons
            # in memory. Each archive also contains decades of unrelated rows.
            rows = [row for row in csv.DictReader(handle) if row.get("season") in SEASONS]
        snapshots.append({"metadata": item, "as_of": as_of, "rows": rows})
    if not snapshots:
        raise ValueError("No complete pinned snapshots")
    return snapshots


def rebuild(index_path: Path, cache: Path, output: Path, fetch_missing=False) -> dict:
    snapshots = load_snapshots(index_path, cache, fetch_missing)
    final = {r["game_id"]: r for r in snapshots[-1]["rows"]}
    pregame, labels = {}, {}
    rejected = Counter()
    for snap in snapshots:
        as_of, meta = snap["as_of"], snap["metadata"]
        for row in snap["rows"]:
            game = row.get("game_id")
            reference = final.get(game)
            if reference is None:
                continue
            try:
                start = event_time(row)
            except (KeyError, ValueError):
                rejected["missing_or_invalid_start"] += 1
                continue
            if not same_event(row, reference):
                rejected["schedule_or_team_revision"] += 1
                continue
            scores, final_scores = score(row), score(reference)
            if final_scores is None or final_scores[0] == final_scores[1]:
                continue
            # Use a genuinely observed later snapshot. Never invent game-end
            # time, assign today's final score to kickoff, or use a 99% price.
            if as_of >= start + timedelta(hours=24) and scores == final_scores:
                labels.setdefault(game, {"as_of": as_of, "meta": meta, "row": row, "scores": scores})
            if not as_of < start <= as_of + timedelta(days=7):
                continue
            if not all(row.get(k, "") in MISSING for k in ("home_score", "away_score", "result", "total")):
                rejected["pregame_record_contains_score"] += 1
                continue
            try:
                home = implied(number(row, "home_moneyline"))
                away = implied(number(row, "away_moneyline"))
                probability = home / (home + away)
                spread, total = -number(row, "spread_line"), number(row, "total_line")
                if not 0 < probability < 1 or total <= 0:
                    raise ValueError("Invalid pregame features")
            except (KeyError, ValueError, ZeroDivisionError):
                rejected["missing_or_invalid_pregame_market"] += 1
                continue
            pregame[game] = {"as_of": as_of, "start": start, "meta": meta, "row": row,
                             "probability": probability, "spread": spread, "total": total}

    output.mkdir(parents=True, exist_ok=True)
    canonical, provenance, settled = [], [], []
    season_counts = Counter()
    for game, pre in sorted(pregame.items(), key=lambda x: (x[1]["as_of"], x[0])):
        label = labels.get(game)
        if label is None:
            rejected["no_matching_later_score_snapshot"] += 1
            continue
        if not pre["as_of"] < pre["start"] < label["as_of"]:
            raise ValueError(f"Chronology violation: {game}")
        home, away = label["scores"]
        event_id = f"nflverse:{game}"
        canonical.append({
            "sport": "NFL", "event_id": event_id, "event_time": pre["start"].isoformat(),
            "as_of": pre["as_of"].isoformat(), "home_team": pre["row"]["home_team"],
            "away_team": pre["row"]["away_team"], "target_home_win": int(home > away),
            "label_available_at": label["as_of"].isoformat(),
            "market_home_probability": format(pre["probability"], ".15g"),
            "consensus_de_vig_home_probability": format(pre["probability"], ".15g"),
            "home_spread": pre["spread"], "consensus_total": pre["total"],
        })
        provenance.append({
            "event_id": event_id, "source_game_id": game,
            "pregame_commit": pre["meta"]["sha"], "pregame_csv_sha256": pre["meta"]["raw_sha256"],
            "score_commit": label["meta"]["sha"], "score_csv_sha256": label["meta"]["raw_sha256"],
            "pregame_record": pre["row"], "score_record": label["row"],
            "as_of_basis": "upstream_git_committer_time",
            "label_time_basis": "first_sampled_archived_score_matching_final_reference_after_24h",
            "home_spread_transform": "negative_of_nflverse_spread_line",
            "market_probability_transform": "multiplicative_devig_of_archived_home_and_away_moneyline",
        })
        settled.append({"event_id": event_id, "home_score": home, "away_score": away,
                        "target_home_win": int(home > away), "label_available_at": label["as_of"].isoformat(),
                        "source_commit": label["meta"]["sha"], "source_csv_sha256": label["meta"]["raw_sha256"]})
        season_counts[pre["row"]["season"]] += 1

    dataset_path = output / "nfl.csv"
    with dataset_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(canonical)
    for filename, records in (("nfl_provenance.jsonl", provenance), ("nfl_labels.jsonl", settled)):
        (output / filename).write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records))
    sources = [{"path": f"raw/{s['metadata']['raw_file']}", "sha256": s["metadata"]["raw_sha256"],
                "bytes": s["metadata"]["raw_bytes"], "commit": s["metadata"]["sha"],
                "as_of": s["metadata"]["as_of"], "url": s["metadata"]["url"]} for s in snapshots]
    limitations = [
        "Archive committer timestamps are upstream metadata, not independently witnessed publication receipts.",
        "Moneylines have archive availability times; original sportsbook quote/update times are unavailable.",
        "Score observations are delayed weekly archive records matched to the final reference, not exact game-end times.",
        "This is a standalone research corpus. It is not merged with differently keyed legacy events.",
    ]
    manifest = {"schema_version": 1, "sport": "NFL", "rows": len(canonical),
                "canonical_file": "nfl.csv", "canonical_sha256": digest(dataset_path),
                "labels_sha256": digest(output / "nfl_labels.jsonl"),
                "provenance_sha256": digest(output / "nfl_provenance.jsonl"),
                "source_index_sha256": digest(index_path), "pregame_sources": sources,
                "score_reference_commit": snapshots[-1]["metadata"]["sha"],
                "source": "nflverse/nfldata, maintained by Lee Sharpe and nflverse",
                "source_dictionary": "https://github.com/nflverse/nfldata/blob/master/DATASETS.md",
                "source_licence_note": "NFL data belong to their respective owners and are governed by their terms of use.",
                "promotion_ready": False, "independent_publication_timestamp_verified": False,
                "limitations": limitations}
    (output / "nfl_source_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    summary = {"rows": len(canonical), "by_season": dict(sorted(season_counts.items())),
               "snapshot_count": len(snapshots), "dataset_sha256": manifest["canonical_sha256"],
               "pregame_candidates": len(pregame), "rejections_or_exclusions": dict(sorted(rejected.items())),
               "as_of_lt_event_time": all(utc(r["as_of"]) < utc(r["event_time"]) for r in canonical),
               "label_after_event": all(utc(r["label_available_at"]) > utc(r["event_time"]) for r in canonical),
               "promotion_ready": False, "limitations": limitations}
    (output / "recovery_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--fetch-missing", action="store_true")
    args = parser.parse_args()
    print(json.dumps(rebuild(args.index, args.cache, args.output_dir, args.fetch_missing), indent=2))


if __name__ == "__main__":
    main()
