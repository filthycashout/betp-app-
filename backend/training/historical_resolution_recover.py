from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

from historical_backfill import (
    COLUMNS,
    SPORTS,
    _canonical,
    _iso,
    _latest_pregame_odds,
    _sha256,
)


def _resolved_side(
    db: sqlite3.Connection,
    condition_id: str,
    event_time: int,
) -> tuple[bool, int] | None:
    rows = list(
        db.execute(
            """
            SELECT timestamp, team_a_price, team_b_price
            FROM sports_price_history
            WHERE condition_id = ?
              AND timestamp > ?
              AND team_a_price IS NOT NULL
              AND team_b_price IS NOT NULL
              AND (
                    (team_a_price >= 0.99 AND team_b_price <= 0.01)
                 OR (team_b_price >= 0.99 AND team_a_price <= 0.01)
              )
            ORDER BY timestamp
            """,
            (condition_id, event_time),
        )
    )
    if not rows:
        return None
    observed: set[bool] = set()
    first_by_side: dict[bool, int] = {}
    for timestamp, a, b in rows:
        if float(a) >= 0.99 and float(b) <= 0.01:
            side = True
        elif float(b) >= 0.99 and float(a) <= 0.01:
            side = False
        else:
            continue
        observed.add(side)
        first_by_side.setdefault(side, int(timestamp))
    if len(observed) != 1:
        return None
    side = next(iter(observed))
    return side, first_by_side[side]


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in COLUMNS})


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def recover(db_path: Path, output_dir: Path, min_match_score: float) -> dict[str, Any]:
    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row
    source_db_sha256 = _sha256(db_path)
    report: dict[str, Any] = {
        "schema_version": 1,
        "method": "postevent_extreme_price_resolution_crosschecked_against_matched_home_away_mapping",
        "minimum_match_score": min_match_score,
        "sports": {},
        "rejected": {},
    }

    def reject(reason: str) -> None:
        report["rejected"][reason] = report["rejected"].get(reason, 0) + 1

    try:
        candidates = list(
            db.execute(
                """
                SELECT
                    sm.condition_id,
                    UPPER(sm.sport) AS sport,
                    sm.team_a,
                    sm.team_b,
                    sm.winner,
                    me.odds_event_id,
                    me.poly_team_a_is_home,
                    me.match_score,
                    MIN(os.commence_time) AS commence_time,
                    MIN(os.home_team) AS home_team,
                    MIN(os.away_team) AS away_team
                FROM matched_events AS me
                JOIN sports_markets AS sm
                  ON sm.condition_id = me.condition_id
                JOIN odds_snapshots AS os
                  ON os.odds_event_id = me.odds_event_id
                WHERE UPPER(sm.sport) IN ('NFL','NBA','MLB','NHL')
                  AND me.poly_team_a_is_home IS NOT NULL
                  AND me.match_score IS NOT NULL
                GROUP BY
                    sm.condition_id, sm.sport, sm.team_a, sm.team_b, sm.winner,
                    me.odds_event_id, me.poly_team_a_is_home, me.match_score
                ORDER BY UPPER(sm.sport), MIN(os.commence_time), me.odds_event_id
                """
            )
        )

        for sport in SPORTS:
            csv_path = output_dir / f"{sport.lower()}.csv"
            manifest_path = output_dir / f"{sport.lower()}_source_manifest.json"
            provenance_path = output_dir / f"{sport.lower()}_provenance.jsonl"
            rows = _read_csv(csv_path)
            provenance = _read_jsonl(provenance_path)
            by_event = {str(row["event_id"]): row for row in rows}
            provenance_by_event = {str(row.get("event_id")): row for row in provenance}
            recovered = 0

            for event in candidates:
                if str(event["sport"]).upper() != sport:
                    continue
                try:
                    score = float(event["match_score"])
                except (TypeError, ValueError):
                    reject("INVALID_MATCH_SCORE")
                    continue
                if score < min_match_score:
                    reject("MATCH_SCORE_BELOW_THRESHOLD")
                    continue
                if event["commence_time"] is None:
                    reject("MISSING_COMMENCE_TIME")
                    continue
                event_time = int(event["commence_time"])
                odds_event_id = str(event["odds_event_id"] or "").strip()
                condition_id = str(event["condition_id"] or "").strip()
                if not odds_event_id or not condition_id:
                    reject("MISSING_EVENT_ID")
                    continue
                event_id = f"hist-oddsapi-{odds_event_id}"
                if event_id in by_event:
                    continue

                resolved = _resolved_side(db, condition_id, event_time)
                if resolved is None:
                    reject("NO_UNAMBIGUOUS_POSTEVENT_RESOLUTION")
                    continue
                winner_is_a, settlement_ts = resolved
                if settlement_ts <= event_time:
                    reject("LABEL_AVAILABILITY_FAILURE")
                    continue

                stored_winner = str(event["winner"] or "").strip()
                team_a = str(event["team_a"] or "").strip()
                team_b = str(event["team_b"] or "").strip()
                if stored_winner == team_a:
                    stored_side: bool | None = True
                elif stored_winner == team_b:
                    stored_side = False
                else:
                    stored_side = None
                if stored_side is not None and stored_side != winner_is_a:
                    reject("STORED_WINNER_CONFLICTS_WITH_PRICE_RESOLUTION")
                    continue

                odds = _latest_pregame_odds(db, odds_event_id, event_time)
                if odds is None:
                    reject("NO_VERIFIED_PREGAME_ODDS")
                    continue
                snapshot_ts, probability, books = odds
                if snapshot_ts >= event_time:
                    reject("CHRONOLOGY_FAILURE")
                    continue

                home_team = str(event["home_team"] or "").strip()
                away_team = str(event["away_team"] or "").strip()
                if not home_team or not away_team:
                    reject("MISSING_TEAM")
                    continue

                team_a_is_home = bool(int(event["poly_team_a_is_home"]))
                target_home_win = int(
                    (winner_is_a and team_a_is_home)
                    or ((not winner_is_a) and (not team_a_is_home))
                )
                row = {
                    "sport": sport,
                    "event_id": event_id,
                    "event_time": _iso(event_time),
                    "as_of": _iso(snapshot_ts),
                    "home_team": home_team,
                    "away_team": away_team,
                    "target_home_win": target_home_win,
                    "label_available_at": _iso(settlement_ts),
                    "market_home_probability": f"{probability:.12f}",
                    "consensus_de_vig_home_probability": f"{probability:.12f}",
                    "home_spread": "",
                    "consensus_total": "",
                }
                by_event[event_id] = row
                provenance_by_event[event_id] = {
                    "event_id": event_id,
                    "source_condition_id": condition_id,
                    "source_odds_event_id": odds_event_id,
                    "match_score": score,
                    "event_time_unix": event_time,
                    "pregame_snapshot_unix": snapshot_ts,
                    "label_observed_unix": settlement_ts,
                    "bookmakers": books,
                    "label_method": "unambiguous_postevent_market_price_resolution_0.99_0.01",
                    "stored_winner_crosscheck": (
                        "MATCH" if stored_side is not None else "NOT_USABLE"
                    ),
                    "probability_method": "mean_multiplicative_devig_across_books_at_latest_verified_pregame_snapshot",
                    "source_database_sha256": source_db_sha256,
                }
                recovered += 1

            merged_rows = sorted(
                by_event.values(), key=lambda row: (row["event_time"], row["event_id"])
            )
            merged_provenance = sorted(
                provenance_by_event.values(),
                key=lambda row: (int(row.get("event_time_unix") or 0), str(row.get("event_id") or "")),
            )
            _write_csv(csv_path, merged_rows)
            _write_jsonl(provenance_path, merged_provenance)

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["rows"] = len(merged_rows)
            manifest["canonical_sha256"] = _sha256(csv_path)
            manifest["provenance_sha256"] = _sha256(provenance_path)
            manifest["resolution_recovery"] = {
                "recovered_rows": recovered,
                "label_method": "unambiguous_postevent_market_price_resolution_0.99_0.01",
                "stored_winner_conflict_rejected": True,
            }
            manifest_path.write_bytes(_canonical(manifest))
            report["sports"][sport] = {
                "rows": len(merged_rows),
                "recovered_rows": recovered,
                "canonical_sha256": manifest["canonical_sha256"],
                "provenance_sha256": manifest["provenance_sha256"],
            }

        summary_path = output_dir / "backfill_summary.json"
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        else:
            summary = {"schema_version": 1}
        summary["resolution_recovery"] = report
        for sport in SPORTS:
            if "sports" not in summary:
                summary["sports"] = {}
            summary["sports"].setdefault(sport, {})
            summary["sports"][sport].update(report["sports"][sport])
        summary_path.write_bytes(_canonical(summary))
        return report
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--min-match-score", type=float, default=0.90)
    args = parser.parse_args()
    report = recover(args.db, args.output_dir, args.min_match_score)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
