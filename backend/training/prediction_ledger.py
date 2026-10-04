from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from evidence_pipeline import (
    ESPN,
    _canonical,
    _espn_results,
    _mlb_results,
    _nhl_results,
    _parse_time,
    _sha256,
)

SPORTS = ("NFL", "NBA", "MLB", "NHL")


def _hash_record(value: dict[str, Any]) -> str:
    payload = {k: v for k, v in value.items() if k != "record_sha256"}
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _date_for(row: dict[str, Any]):
    raw = row.get("schedule_date")
    if raw:
        return datetime.fromisoformat(str(raw)).date()
    return _parse_time(str(row["event_time"])).date()


def _all_prediction_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    base = root / "prediction_ledger" / "pregame"
    if not base.exists():
        return rows
    for path in sorted(base.rglob("predictions_*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def capture(root: Path, capture_dir: Path) -> None:
    ledger_root = root / "prediction_ledger" / "pregame"
    written = []
    for raw_path in sorted(capture_dir.glob("powerhouse_raw_*.json")):
        doc = json.loads(raw_path.read_text(encoding="utf-8"))
        fetched_at = _parse_time(str(doc["fetched_at"]))
        payload = doc.get("payload") or {}
        stamp = fetched_at.strftime("%Y%m%dT%H%M%SZ")
        day_dir = ledger_root / fetched_at.strftime("%Y/%m/%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        out_path = day_dir / f"predictions_{stamp}.jsonl"
        manifest_path = day_dir / f"predictions_{stamp}_manifest.json"

        rows = []
        for game in payload.get("games") or []:
            sport = str(game.get("sport") or "").upper()
            event_id = str(game.get("event_id") or "")
            event_time = game.get("event_time")
            if sport not in SPORTS or not event_id or not event_time:
                continue
            try:
                event_dt = _parse_time(str(event_time))
            except Exception:
                continue
            if fetched_at >= event_dt:
                continue

            market = game.get("market") or {}
            model = game.get("model_metadata") or {}
            gate = model.get("promotion_gate") or {}
            predictions = game.get("predictions") or {}
            row = {
                "schema_version": 1,
                "sport": sport,
                "event_id": event_id,
                "event_time": event_dt.isoformat(),
                "schedule_date": game.get("date"),
                "as_of": fetched_at.isoformat(),
                "home_team": game.get("home"),
                "away_team": game.get("away"),
                "exact_pick": game.get("pick"),
                "home_win_probability": game.get("home_win_probability"),
                "probability_source": game.get("probability_source"),
                "prediction_reasoning": game.get("prediction_reasoning"),
                "predictions": predictions,
                "projected_score": game.get("projected_score"),
                "model_status": game.get("model_status"),
                "model_id": model.get("active_model_id") or model.get("model_id") or model.get("version"),
                "model_artifact_sha256": gate.get("artifact_sha256") or model.get("sha256"),
                "promotion_gate_passed": gate.get("passed") is True,
                "market": market,
                "market_last_update": market.get("last_update"),
                "moneyline_last_update": market.get("moneyline_last_update"),
                "spread_last_update": market.get("spread_last_update"),
                "total_last_update": market.get("total_last_update"),
                "market_books_used": market.get("books_used") or [],
                "source_backend": str(doc.get("source_url") or "").split("/v1/", 1)[0],
                "source_raw_file": raw_path.name,
                "source_raw_sha256": _sha256(raw_path),
            }
            row["record_sha256"] = _hash_record(row)
            rows.append(row)

        rows.sort(key=lambda x: (x["sport"], x["event_time"], x["event_id"]))
        with out_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        manifest = {
            "schema_version": 1,
            "capture_type": "exact_app_prediction_ledger",
            "captured_at": fetched_at.isoformat(),
            "source_raw_file": raw_path.name,
            "source_raw_sha256": _sha256(raw_path),
            "ledger_file": str(out_path.relative_to(root)),
            "ledger_sha256": _sha256(out_path),
            "rows": len(rows),
            "chronology_rule": "as_of < event_time",
            "secrets_embedded": False,
        }
        manifest_path.write_bytes(_canonical(manifest))
        written.append(manifest)
    print(json.dumps({"prediction_ledger_captures": written}, indent=2, sort_keys=True))


def settle(root: Path, lookback_days: int = 21) -> None:
    rows = _all_prediction_rows(root)
    today = datetime.now(timezone.utc).date()
    out_dir = root / "prediction_ledger" / "settled"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "settlements.jsonl"

    settlements: dict[str, dict[str, Any]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                settlements[item["record_sha256"]] = item

    requested: dict[tuple[str, Any], set[str]] = {}
    for row in rows:
        try:
            game_date = _date_for(row)
        except Exception:
            continue
        if game_date > today or game_date < today - timedelta(days=lookback_days):
            continue
        requested.setdefault((row["sport"], game_date), set()).add(row["event_id"])

    results: dict[tuple[str, Any], dict[str, int]] = {}
    for sport, game_date in sorted(requested, key=lambda x: (x[1], x[0])):
        try:
            if sport in ESPN:
                results[(sport, game_date)] = _espn_results(sport, game_date)
            elif sport == "MLB":
                results[(sport, game_date)] = _mlb_results(game_date)
            elif sport == "NHL":
                results[(sport, game_date)] = _nhl_results(game_date)
        except Exception:
            results[(sport, game_date)] = {}

    now = datetime.now(timezone.utc).isoformat()
    for row in rows:
        record_sha = row.get("record_sha256")
        if not record_sha or record_sha in settlements:
            continue
        try:
            game_date = _date_for(row)
        except Exception:
            continue
        target = results.get((row["sport"], game_date), {}).get(row["event_id"])
        if target is None:
            continue
        pick = str(row.get("exact_pick") or "")
        home = str(row.get("home_team") or "")
        away = str(row.get("away_team") or "")
        correct = None
        if pick and home and away:
            correct = bool((target == 1 and pick == home) or (target == 0 and pick == away))
        item = {
            "schema_version": 1,
            "record_sha256": record_sha,
            "sport": row["sport"],
            "event_id": row["event_id"],
            "event_time": row["event_time"],
            "as_of": row["as_of"],
            "exact_pick": row.get("exact_pick"),
            "model_id": row.get("model_id"),
            "model_artifact_sha256": row.get("model_artifact_sha256"),
            "market_last_update": row.get("market_last_update"),
            "target_home_win": target,
            "prediction_correct": correct,
            "settled_at": now,
            "result_source": (
                "ESPN scoreboard"
                if row["sport"] in ESPN
                else "MLB Stats API"
                if row["sport"] == "MLB"
                else "NHL Web API"
            ),
        }
        item["settlement_sha256"] = hashlib.sha256(_canonical(item)).hexdigest()
        settlements[record_sha] = item

    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for item in sorted(
            settlements.values(),
            key=lambda x: (x["sport"], x["event_time"], x["as_of"], x["event_id"]),
        ):
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    tmp.replace(path)
    print(json.dumps({"settled_prediction_records": len(settlements), "sha256": _sha256(path)}, indent=2))


def verify(root: Path) -> None:
    rows = _all_prediction_rows(root)
    chronology_failures = []
    hash_failures = []
    missing_model_identity = []
    for row in rows:
        if _hash_record(row) != row.get("record_sha256"):
            hash_failures.append(row.get("record_sha256"))
        try:
            if _parse_time(str(row["as_of"])) >= _parse_time(str(row["event_time"])):
                chronology_failures.append(row.get("record_sha256"))
        except Exception:
            chronology_failures.append(row.get("record_sha256"))
        if not row.get("model_id") or not row.get("model_artifact_sha256"):
            missing_model_identity.append(row.get("record_sha256"))

    settlement_path = root / "prediction_ledger" / "settled" / "settlements.jsonl"
    settled = []
    if settlement_path.exists():
        settled = [
            json.loads(line)
            for line in settlement_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    known = {row.get("record_sha256") for row in rows}
    orphaned = [row.get("record_sha256") for row in settled if row.get("record_sha256") not in known]
    by_sport = {}
    for sport in SPORTS:
        sport_rows = [x for x in rows if x.get("sport") == sport]
        sport_settled = [x for x in settled if x.get("sport") == sport]
        scored = [x for x in sport_settled if x.get("prediction_correct") is not None]
        by_sport[sport] = {
            "pregame_records": len(sport_rows),
            "settled_records": len(sport_settled),
            "scored_moneyline_records": len(scored),
            "correct_moneyline_records": sum(1 for x in scored if x.get("prediction_correct") is True),
        }

    report = {
        "schema_version": 1,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "passed": not chronology_failures and not hash_failures and not orphaned and not missing_model_identity,
        "pregame_records": len(rows),
        "settled_records": len(settled),
        "chronology_failures": chronology_failures,
        "record_hash_failures": hash_failures,
        "orphaned_settlements": orphaned,
        "missing_model_identity": missing_model_identity,
        "sports": by_sport,
        "settlements_sha256": _sha256(settlement_path) if settlement_path.exists() else None,
    }
    out = root / "prediction_ledger" / "verification.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(_canonical(report))
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["passed"]:
        raise SystemExit(2)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("capture")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--capture-dir", type=Path, required=True)

    p = sub.add_parser("settle")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--lookback-days", type=int, default=21)

    p = sub.add_parser("verify")
    p.add_argument("--root", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "capture":
        capture(args.root, args.capture_dir)
    elif args.command == "settle":
        settle(args.root, args.lookback_days)
    else:
        verify(args.root)


if __name__ == "__main__":
    main()
