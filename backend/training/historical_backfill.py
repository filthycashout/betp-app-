from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SPORTS = ("NFL", "NBA", "MLB", "NHL")
COLUMNS = [
    "sport",
    "event_id",
    "event_time",
    "as_of",
    "home_team",
    "away_team",
    "target_home_win",
    "label_available_at",
    "market_home_probability",
    "consensus_de_vig_home_probability",
    "home_spread",
    "consensus_total",
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def _iso(ts: int | float) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _devig_home(home_odds: float, away_odds: float) -> float:
    if home_odds <= 1.0 or away_odds <= 1.0:
        raise ValueError("Decimal moneyline odds must be greater than 1")
    hp = 1.0 / home_odds
    ap = 1.0 / away_odds
    return hp / (hp + ap)


def _table_columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in db.execute(f"PRAGMA table_info({table})")}


def _require_schema(db: sqlite3.Connection) -> None:
    required = {
        "sports_markets": {
            "condition_id", "sport", "team_a", "team_b", "winner", "game_start_time"
        },
        "sports_price_history": {
            "condition_id", "timestamp", "team_a_price", "team_b_price"
        },
        "odds_snapshots": {
            "odds_event_id", "sport", "home_team", "away_team",
            "commence_time", "snapshot_ts", "home_odds", "away_odds", "bookmaker"
        },
        "matched_events": {
            "condition_id", "odds_event_id", "poly_team_a_is_home", "match_score"
        },
    }
    for table, columns in required.items():
        observed = _table_columns(db, table)
        missing = sorted(columns - observed)
        if missing:
            raise ValueError(f"{table} missing required columns: {missing}")


def _settlement_timestamp(
    db: sqlite3.Connection,
    condition_id: str,
    winner_is_a: bool,
    event_time: int,
) -> int | None:
    winner_col = "team_a_price" if winner_is_a else "team_b_price"
    loser_col = "team_b_price" if winner_is_a else "team_a_price"
    row = db.execute(
        f"""
        SELECT MIN(timestamp)
        FROM sports_price_history
        WHERE condition_id = ?
          AND timestamp > ?
          AND {winner_col} IS NOT NULL
          AND {loser_col} IS NOT NULL
          AND {winner_col} >= 0.99
          AND {loser_col} <= 0.01
        """,
        (condition_id, event_time),
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _latest_pregame_odds(
    db: sqlite3.Connection,
    odds_event_id: str,
    event_time: int,
) -> tuple[int, float, list[str]] | None:
    row = db.execute(
        """
        SELECT MAX(snapshot_ts)
        FROM odds_snapshots
        WHERE odds_event_id = ?
          AND snapshot_ts < ?
          AND home_odds IS NOT NULL
          AND away_odds IS NOT NULL
          AND home_odds > 1.0
          AND away_odds > 1.0
        """,
        (odds_event_id, event_time),
    ).fetchone()
    if not row or row[0] is None:
        return None
    snapshot_ts = int(row[0])
    quotes = list(
        db.execute(
            """
            SELECT home_odds, away_odds, bookmaker
            FROM odds_snapshots
            WHERE odds_event_id = ?
              AND snapshot_ts = ?
              AND home_odds IS NOT NULL
              AND away_odds IS NOT NULL
              AND home_odds > 1.0
              AND away_odds > 1.0
            ORDER BY bookmaker
            """,
            (odds_event_id, snapshot_ts),
        )
    )
    probabilities: list[float] = []
    books: list[str] = []
    for home_odds, away_odds, bookmaker in quotes:
        try:
            probabilities.append(_devig_home(float(home_odds), float(away_odds)))
            books.append(str(bookmaker or "unknown"))
        except (TypeError, ValueError, ZeroDivisionError):
            continue
    if not probabilities:
        return None
    return snapshot_ts, sum(probabilities) / len(probabilities), sorted(set(books))


def _extract(
    db_path: Path,
    output_dir: Path,
    source_url: str,
    source_asset_sha256: str,
    source_release: str,
    min_match_score: float,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    db_sha256 = _sha256(db_path)
    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row
    try:
        _require_schema(db)
        events = list(
            db.execute(
                """
                SELECT
                    sm.condition_id,
                    UPPER(sm.sport) AS sport,
                    sm.team_a,
                    sm.team_b,
                    sm.winner,
                    sm.game_start_time,
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
                WHERE UPPER(sm.sport) IN ('NFL', 'NBA', 'MLB', 'NHL')
                  AND sm.winner IS NOT NULL
                  AND TRIM(sm.winner) != ''
                  AND me.poly_team_a_is_home IS NOT NULL
                  AND me.match_score IS NOT NULL
                GROUP BY
                    sm.condition_id, sm.sport, sm.team_a, sm.team_b, sm.winner,
                    sm.game_start_time, me.odds_event_id,
                    me.poly_team_a_is_home, me.match_score
                ORDER BY UPPER(sm.sport), MIN(os.commence_time), me.odds_event_id
                """
            )
        )

        rows_by_sport: dict[str, list[dict[str, Any]]] = {sport: [] for sport in SPORTS}
        provenance_by_sport: dict[str, list[dict[str, Any]]] = {sport: [] for sport in SPORTS}
        rejected: dict[str, int] = {}
        seen_event_ids: set[str] = set()

        def reject(reason: str) -> None:
            rejected[reason] = rejected.get(reason, 0) + 1

        for event in events:
            sport = str(event["sport"]).upper()
            if sport not in SPORTS:
                continue
            try:
                match_score = float(event["match_score"])
            except (TypeError, ValueError):
                reject("INVALID_MATCH_SCORE")
                continue
            if match_score < min_match_score:
                reject("MATCH_SCORE_BELOW_THRESHOLD")
                continue

            event_time = event["commence_time"]
            if event_time is None:
                reject("MISSING_COMMENCE_TIME")
                continue
            event_time = int(event_time)
            odds_event_id = str(event["odds_event_id"] or "").strip()
            condition_id = str(event["condition_id"] or "").strip()
            if not odds_event_id or not condition_id:
                reject("MISSING_EVENT_ID")
                continue

            team_a = str(event["team_a"] or "").strip()
            team_b = str(event["team_b"] or "").strip()
            winner = str(event["winner"] or "").strip()
            if winner == team_a:
                winner_is_a = True
            elif winner == team_b:
                winner_is_a = False
            else:
                reject("WINNER_NOT_BINARY_TEAM")
                continue

            team_a_is_home = bool(int(event["poly_team_a_is_home"]))
            target_home_win = int(
                (winner_is_a and team_a_is_home)
                or ((not winner_is_a) and (not team_a_is_home))
            )

            odds = _latest_pregame_odds(db, odds_event_id, event_time)
            if odds is None:
                reject("NO_VERIFIED_PREGAME_ODDS")
                continue
            snapshot_ts, probability, books = odds
            if snapshot_ts >= event_time:
                reject("CHRONOLOGY_FAILURE")
                continue

            settlement_ts = _settlement_timestamp(
                db, condition_id, winner_is_a, event_time
            )
            if settlement_ts is None:
                reject("NO_POSTEVENT_RESOLUTION_TIMESTAMP")
                continue
            if settlement_ts <= event_time:
                reject("LABEL_AVAILABILITY_FAILURE")
                continue

            event_id = f"hist-oddsapi-{odds_event_id}"
            if event_id in seen_event_ids:
                reject("DUPLICATE_EVENT_ID")
                continue
            seen_event_ids.add(event_id)

            home_team = str(event["home_team"] or "").strip()
            away_team = str(event["away_team"] or "").strip()
            if not home_team or not away_team:
                reject("MISSING_TEAM")
                continue

            canonical = {
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
            rows_by_sport[sport].append(canonical)
            provenance_by_sport[sport].append(
                {
                    "event_id": event_id,
                    "source_condition_id": condition_id,
                    "source_odds_event_id": odds_event_id,
                    "match_score": match_score,
                    "event_time_unix": event_time,
                    "pregame_snapshot_unix": snapshot_ts,
                    "label_observed_unix": settlement_ts,
                    "bookmakers": books,
                    "probability_method": "mean_multiplicative_devig_across_books_at_latest_verified_pregame_snapshot",
                    "source_database_sha256": db_sha256,
                }
            )

        summary: dict[str, Any] = {
            "schema_version": 1,
            "source": {
                "repository": "ADnocap/taut-arb-backtest",
                "release": source_release,
                "asset_url": source_url,
                "asset_sha256": source_asset_sha256,
                "database_sha256": db_sha256,
                "upstream_repository_license": None,
                "license_note": (
                    "Upstream repository exposes the dataset publicly but declares no GitHub license. "
                    "PhilthySports records provenance and does not vendor the source database."
                ),
            },
            "eligibility_rule": (
                "snapshot_ts < commence_time AND an observed post-event resolved "
                "Polymarket price timestamp consistent with the stored winner"
            ),
            "minimum_match_score": min_match_score,
            "sports": {},
            "rejected": dict(sorted(rejected.items())),
        }

        for sport in SPORTS:
            rows = sorted(
                rows_by_sport[sport],
                key=lambda item: (item["event_time"], item["event_id"]),
            )
            provenance = sorted(
                provenance_by_sport[sport],
                key=lambda item: (item["event_time_unix"], item["event_id"]),
            )
            csv_path = output_dir / f"{sport.lower()}.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=COLUMNS)
                writer.writeheader()
                writer.writerows(rows)

            provenance_path = output_dir / f"{sport.lower()}_provenance.jsonl"
            with provenance_path.open("w", encoding="utf-8") as handle:
                for item in provenance:
                    handle.write(json.dumps(item, sort_keys=True) + "\n")

            manifest = {
                "schema_version": 1,
                "sport": sport,
                "rows": len(rows),
                "canonical_file": csv_path.name,
                "canonical_sha256": _sha256(csv_path),
                "provenance_file": provenance_path.name,
                "provenance_sha256": _sha256(provenance_path),
                "source_asset_sha256": source_asset_sha256,
                "source_database_sha256": db_sha256,
                "source_url": source_url,
                "source_release": source_release,
                "promotion_eligible": True,
                "chronology_verified": True,
                "label_availability_verified": True,
                "missing_runtime_features": ["home_spread", "consensus_total"],
                "missing_feature_policy": "leave_missing_for_in_fold_imputation;never_fabricate",
                "eligibility_rule": summary["eligibility_rule"],
                "minimum_match_score": min_match_score,
            }
            manifest_path = output_dir / f"{sport.lower()}_source_manifest.json"
            manifest_path.write_bytes(_canonical(manifest))
            summary["sports"][sport] = {
                "rows": len(rows),
                "canonical_sha256": manifest["canonical_sha256"],
                "provenance_sha256": manifest["provenance_sha256"],
            }

        summary_path = output_dir / "backfill_summary.json"
        summary_path.write_bytes(_canonical(summary))
        return summary
    finally:
        db.close()


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _validate_row(row: dict[str, str], sport: str) -> None:
    missing = [column for column in COLUMNS if column not in row]
    if missing:
        raise ValueError(f"{sport} historical row missing columns: {missing}")
    if str(row.get("sport") or "").upper() != sport:
        raise ValueError(f"{sport} historical row has wrong sport")
    event_time = _parse_time(row["event_time"])
    as_of = _parse_time(row["as_of"])
    label_available = _parse_time(row["label_available_at"])
    if not as_of < event_time:
        raise ValueError(f"{sport} historical chronology failure: {row['event_id']}")
    if not label_available > event_time:
        raise ValueError(f"{sport} historical label availability failure: {row['event_id']}")
    probability = float(row["market_home_probability"])
    consensus = float(row["consensus_de_vig_home_probability"])
    if not (0.0 < probability < 1.0 and 0.0 < consensus < 1.0):
        raise ValueError(f"{sport} historical probability outside (0,1)")
    if int(row["target_home_win"]) not in (0, 1):
        raise ValueError(f"{sport} historical target is not binary")


def _hash_struct(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _merge(root: Path) -> dict[str, Any]:
    canonical_dir = root / "canonical"
    approved_root = root / "historical" / "approved"
    if not canonical_dir.exists():
        raise ValueError("Live canonical directory does not exist")
    approved_dirs = sorted(path for path in approved_root.glob("*") if path.is_dir())
    result: dict[str, Any] = {"sports": {}, "historical_sources": []}

    for sport in SPORTS:
        live_csv = canonical_dir / f"{sport.lower()}.csv"
        manifest_path = canonical_dir / f"{sport.lower()}_source_manifest.json"
        if not live_csv.exists() or not manifest_path.exists():
            raise ValueError(f"Missing live canonical evidence for {sport}")

        base_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        combined: dict[str, dict[str, str]] = {}
        for row in _read_rows(live_csv):
            _validate_row(row, sport)
            combined[row["event_id"]] = {column: row.get(column, "") for column in COLUMNS}

        historical_descriptors: list[dict[str, Any]] = []
        historical_label_hashes: list[str] = []
        for directory in approved_dirs:
            csv_path = directory / f"{sport.lower()}.csv"
            hist_manifest_path = directory / f"{sport.lower()}_source_manifest.json"
            if not csv_path.exists() or not hist_manifest_path.exists():
                continue
            hist_manifest = json.loads(hist_manifest_path.read_text(encoding="utf-8"))
            if hist_manifest.get("promotion_eligible") is not True:
                raise ValueError(f"Historical source not promotion eligible: {hist_manifest_path}")
            if hist_manifest.get("chronology_verified") is not True:
                raise ValueError(f"Historical chronology not verified: {hist_manifest_path}")
            if hist_manifest.get("label_availability_verified") is not True:
                raise ValueError(f"Historical label availability not verified: {hist_manifest_path}")
            if hist_manifest.get("canonical_sha256") != _sha256(csv_path):
                raise ValueError(f"Historical canonical checksum mismatch: {csv_path}")
            provenance_path = directory / str(hist_manifest["provenance_file"])
            if hist_manifest.get("provenance_sha256") != _sha256(provenance_path):
                raise ValueError(f"Historical provenance checksum mismatch: {provenance_path}")

            for row in _read_rows(csv_path):
                _validate_row(row, sport)
                event_id = row["event_id"]
                if event_id in combined:
                    existing = combined[event_id]
                    if existing != {column: row.get(column, "") for column in COLUMNS}:
                        raise ValueError(f"Conflicting duplicate historical event: {event_id}")
                    continue
                combined[event_id] = {column: row.get(column, "") for column in COLUMNS}

            descriptor = {
                "path": str(csv_path.relative_to(root)),
                "sha256": _sha256(csv_path),
                "bytes": csv_path.stat().st_size,
                "provenance_path": str(provenance_path.relative_to(root)),
                "provenance_sha256": _sha256(provenance_path),
                "source_asset_sha256": hist_manifest.get("source_asset_sha256"),
                "source_database_sha256": hist_manifest.get("source_database_sha256"),
                "source_url": hist_manifest.get("source_url"),
                "source_release": hist_manifest.get("source_release"),
            }
            historical_descriptors.append(descriptor)
            historical_label_hashes.append(str(hist_manifest.get("provenance_sha256") or ""))

        rows = sorted(
            combined.values(),
            key=lambda item: (item["event_time"], item["event_id"]),
        )
        with live_csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

        existing_sources = list(base_manifest.get("pregame_sources") or [])
        combined_sources = existing_sources + historical_descriptors
        base_labels_sha = base_manifest.get("labels_sha256")
        combined_labels = {
            "live_labels_sha256": base_labels_sha,
            "historical_label_provenance_sha256": sorted(historical_label_hashes),
        }
        base_manifest["rows"] = len(rows)
        base_manifest["canonical_sha256"] = _sha256(live_csv)
        base_manifest["pregame_sources"] = combined_sources
        base_manifest["pregame_source_manifest_sha256"] = _hash_struct(combined_sources)
        base_manifest["historical_sources"] = historical_descriptors
        base_manifest["labels_sha256"] = _hash_struct(combined_labels)
        base_manifest["label_sources"] = combined_labels
        base_manifest["promotion_ready"] = False
        base_manifest["promotion_ready_reason"] = (
            "Canonical live plus checksum-verified historical evidence is ready for "
            "strict v8 sample, chronology, OOF calibration, metric, leakage, parity, "
            "signature, and artifact promotion gates."
        )
        manifest_path.write_bytes(_canonical(base_manifest))
        result["sports"][sport] = {
            "rows": len(rows),
            "canonical_sha256": base_manifest["canonical_sha256"],
            "historical_rows": sum(
                int(json.loads((directory / f"{sport.lower()}_source_manifest.json").read_text()).get("rows", 0))
                for directory in approved_dirs
                if (directory / f"{sport.lower()}_source_manifest.json").exists()
            ),
        }

    result["historical_sources"] = [
        str(path.relative_to(root)) for path in approved_dirs
    ]
    status_path = root / "historical" / "merge_status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_bytes(_canonical(result))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    extract = sub.add_parser("extract")
    extract.add_argument("--db", required=True, type=Path)
    extract.add_argument("--output-dir", required=True, type=Path)
    extract.add_argument("--source-url", required=True)
    extract.add_argument("--source-asset-sha256", required=True)
    extract.add_argument("--source-release", required=True)
    extract.add_argument("--min-match-score", type=float, default=0.90)

    merge = sub.add_parser("merge")
    merge.add_argument("--root", required=True, type=Path)

    args = parser.parse_args()
    if args.command == "extract":
        result = _extract(
            args.db,
            args.output_dir,
            args.source_url,
            args.source_asset_sha256,
            args.source_release,
            args.min_match_score,
        )
    else:
        result = _merge(args.root)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
