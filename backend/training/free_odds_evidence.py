from __future__ import annotations

import argparse
import json
from datetime import date as date_cls
from pathlib import Path
from typing import Any

from evidence.market_snapshot_store import parse_utc, read_market_snapshots
from outcome_validation import results_for_date


def _norm(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _same_team(a: Any, b: Any) -> bool:
    x, y = _norm(a), _norm(b)
    return bool(x and y and (x == y or x in y or y in x))


def _match_result(snapshot: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any] | None:
    event_id = str(snapshot.get("event_id") or "")
    exact = next((row for row in results if event_id and str(row.get("event_id") or "") == event_id), None)
    if exact:
        return exact
    return next((row for row in results if
        _same_team(snapshot.get("home_team"), row.get("home")) and
        _same_team(snapshot.get("away_team"), row.get("away"))), None)


def build_training_evidence(sport: str, day: date_cls) -> list[dict[str, Any]]:
    snapshots = read_market_snapshots(sport=sport, date=day.isoformat(), limit=10000)
    try:
        results = results_for_date(sport, day)
    except Exception:
        results = []
    out = []
    for snapshot in snapshots:
        try:
            chronology_valid = parse_utc(snapshot["fetched_at_utc"]) < parse_utc(snapshot["event_time_utc"])
        except (KeyError, TypeError, ValueError):
            chronology_valid = False
        if not chronology_valid:
            continue
        result = _match_result(snapshot, results)
        if not result or result.get("completed") is not True:
            continue
        out.append({
            "schema_version": "1",
            "sport": sport.upper(),
            "event_id": snapshot.get("event_id"),
            "record_sha256": snapshot.get("record_sha256"),
            "fetched_at_utc": snapshot.get("fetched_at_utc"),
            "event_time_utc": snapshot.get("event_time_utc"),
            "chronology_valid": True,
            "bookmakers": snapshot.get("bookmakers") or [],
            "gateway": snapshot.get("gateway") or {},
            "home_score": result.get("home_score"),
            "away_score": result.get("away_score"),
            "outcome_source": result.get("source"),
        })
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Export chronology-valid FreeOddsGateway training evidence")
    parser.add_argument("--sport", required=True, choices=["NFL", "NBA", "MLB", "NHL"])
    parser.add_argument("--date", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    day = date_cls.fromisoformat(args.date)
    rows = build_training_evidence(args.sport, day)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows) + ("\n" if rows else ""), encoding="utf-8")
    print(json.dumps({"sport": args.sport, "date": args.date, "rows": len(rows), "output": str(path)}))


if __name__ == "__main__":
    main()
