from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import psycopg
    from psycopg.types.json import Jsonb
except Exception:  # optional until runtime requirements are installed
    psycopg = None
    Jsonb = None

_LOCK = threading.RLock()
_DB_LOCK = threading.RLock()
_DB_READY = False
_DEFAULT_ROOT = Path(__file__).resolve().parent / "runtime_market_snapshots"
SNAPSHOT_ROOT = Path(os.environ.get("PHILTHY_MARKET_SNAPSHOT_DIR", str(_DEFAULT_ROOT)))


def _database_url() -> str:
    return (
        os.getenv("PHILTHY_EVIDENCE_DATABASE_URL", "").strip()
        or os.getenv("DATABASE_URL", "").strip()
    )


def parse_utc(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def _ensure_database() -> bool:
    global _DB_READY
    if _DB_READY:
        return True
    url = _database_url()
    if not url or psycopg is None or Jsonb is None:
        return False
    with _DB_LOCK:
        if _DB_READY:
            return True
        try:
            with psycopg.connect(url, autocommit=True, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS philthy_market_snapshots (
                            record_sha256 TEXT PRIMARY KEY,
                            event_date DATE NOT NULL,
                            sport TEXT NOT NULL,
                            event_id TEXT,
                            fetched_at TIMESTAMPTZ NOT NULL,
                            event_time TIMESTAMPTZ NOT NULL,
                            payload JSONB NOT NULL,
                            created_at TIMESTAMPTZ DEFAULT NOW()
                        )
                        """
                    )
                    cur.execute(
                        "CREATE INDEX IF NOT EXISTS philthy_market_snapshots_lookup_idx "
                        "ON philthy_market_snapshots (sport, event_date, fetched_at DESC)"
                    )
            _DB_READY = True
            return True
        except Exception:
            return False


def record_market_snapshot(
    event: dict[str, Any],
    *,
    fetched_at: datetime | None = None,
) -> dict[str, Any] | None:
    """Append one chronology-valid market snapshot.

    A snapshot is accepted only when fetched_at is strictly before event_time.
    The canonical payload hash is the immutable record identity; no update path
    is exposed and duplicate hashes are ignored.
    """
    fetched = (fetched_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        event_time = parse_utc(event.get("commence_time") or event.get("event_time"))
    except (TypeError, ValueError):
        return None
    if fetched >= event_time:
        return None

    sport = str(event.get("sport") or "").upper().strip()
    if not sport:
        return None

    record: dict[str, Any] = {
        "schema_version": "1",
        "sport": sport,
        "event_id": str(event.get("id") or event.get("event_id") or ""),
        "home_team": event.get("home_team") or event.get("home"),
        "away_team": event.get("away_team") or event.get("away"),
        "event_time_utc": _iso(event_time),
        "fetched_at_utc": _iso(fetched),
        "market_source": event.get("market_source"),
        "data_quality": event.get("data_quality"),
        "bookmakers": event.get("bookmakers") or [],
        "gateway": event.get("gateway") or {},
        "secondary_signals": event.get("secondary_signals") or {},
    }
    digest = hashlib.sha256(_canonical_bytes(record)).hexdigest()
    record["record_sha256"] = digest
    event_date = event_time.date().isoformat()

    if _ensure_database():
        try:
            with psycopg.connect(_database_url(), autocommit=True, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO philthy_market_snapshots
                            (record_sha256, event_date, sport, event_id, fetched_at, event_time, payload)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (record_sha256) DO NOTHING
                        """,
                        (
                            digest,
                            event_date,
                            record["sport"],
                            record["event_id"],
                            fetched,
                            event_time,
                            Jsonb(record),
                        ),
                    )
            return record
        except Exception:
            pass

    path = SNAPSHOT_ROOT / event_date / "markets.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        existing = set()
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    old = json.loads(line)
                except ValueError:
                    continue
                if old.get("record_sha256"):
                    existing.add(old["record_sha256"])
        if digest not in existing:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    return record


def read_market_snapshots(
    *,
    sport: str | None = None,
    date: str | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    wanted = sport.upper() if sport else None
    if _ensure_database():
        try:
            clauses: list[str] = []
            params: list[Any] = []
            if wanted:
                clauses.append("sport = %s")
                params.append(wanted)
            if date:
                clauses.append("event_date = %s")
                params.append(date)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            params.append(int(limit))
            with psycopg.connect(_database_url(), autocommit=True, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT payload FROM philthy_market_snapshots"
                        + where
                        + " ORDER BY fetched_at DESC LIMIT %s",
                        params,
                    )
                    rows = cur.fetchall()
            return [row[0] if isinstance(row[0], dict) else json.loads(row[0]) for row in rows]
        except Exception:
            pass

    files = [SNAPSHOT_ROOT / date / "markets.jsonl"] if date else sorted(
        SNAPSHOT_ROOT.glob("*/markets.jsonl"), reverse=True
    )
    out: list[dict[str, Any]] = []
    for path in files:
        if not path.exists():
            continue
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if wanted and row.get("sport") != wanted:
                continue
            out.append(row)
            if len(out) >= limit:
                return out
    return out
