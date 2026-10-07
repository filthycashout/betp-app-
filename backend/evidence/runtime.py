from __future__ import annotations

import json
import os
import threading
import time
import uuid

try:
    import psycopg
    from psycopg.types.json import Jsonb
except Exception:  # optional until backend requirements are installed
    psycopg = None
    Jsonb = None
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from evidence.signal_log import (
    anchor_batch,
    append_jsonl,
    decimal_from_american,
    make_signal,
    parse_utc,
    reason_codes_for,
    verify_merkle_proof,
    verify_signal,
)

router = APIRouter(prefix="/v1/evidence", tags=["evidence"])
_LOCK = threading.RLock()
_DEFAULT_ROOT = Path(__file__).resolve().parent / "runtime_signals"
SIGNAL_ROOT = Path(os.environ.get("PHILTHY_SIGNAL_LOG_DIR", str(_DEFAULT_ROOT)))


_DB_LOCK = threading.RLock()
_DB_READY = False
_DB_ERROR_TYPE: str | None = None
_DB_LOG_STATE: str | None = None


def _database_url() -> str:
    return (
        os.getenv("PHILTHY_EVIDENCE_DATABASE_URL", "").strip()
        or os.getenv("DATABASE_URL", "").strip()
    )


def _log_storage_state(state: str) -> None:
    global _DB_LOG_STATE
    if state != _DB_LOG_STATE:
        print(f"PHILTHY_EVIDENCE_STORAGE:{state}", flush=True)
        _DB_LOG_STATE = state


def _mark_db_failed(exc: Exception) -> None:
    global _DB_READY, _DB_ERROR_TYPE
    _DB_READY = False
    _DB_ERROR_TYPE = type(exc).__name__
    _log_storage_state(f"server_runtime_fallback:{_DB_ERROR_TYPE}")


def _ensure_database() -> bool:
    global _DB_READY, _DB_ERROR_TYPE
    if _DB_READY:
        return True
    url = _database_url()
    if not url:
        _DB_ERROR_TYPE = "DATABASE_URL_MISSING"
        _log_storage_state("server_runtime_fallback:DATABASE_URL_MISSING")
        return False
    if psycopg is None or Jsonb is None:
        _DB_ERROR_TYPE = "PSYCOPG_UNAVAILABLE"
        _log_storage_state("server_runtime_fallback:PSYCOPG_UNAVAILABLE")
        return False
    with _DB_LOCK:
        if _DB_READY:
            return True
        try:
            with psycopg.connect(url, autocommit=True, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    # CREATE TABLE IF NOT EXISTS does not migrate an older table.
                    # Create the current shape and then add columns introduced by
                    # later releases before an index or query can reference them.
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS philthy_evidence_signals (
                            signal_id TEXT PRIMARY KEY,
                            event_date DATE,
                            league TEXT,
                            payload JSONB,
                            created_at TIMESTAMPTZ DEFAULT NOW()
                        )
                        """
                    )
                    for ddl in (
                        "ALTER TABLE philthy_evidence_signals ADD COLUMN IF NOT EXISTS signal_id TEXT",
                        "ALTER TABLE philthy_evidence_signals ADD COLUMN IF NOT EXISTS event_date DATE",
                        "ALTER TABLE philthy_evidence_signals ADD COLUMN IF NOT EXISTS league TEXT",
                        "ALTER TABLE philthy_evidence_signals ADD COLUMN IF NOT EXISTS payload JSONB",
                        "ALTER TABLE philthy_evidence_signals ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()",
                    ):
                        cur.execute(ddl)
                    cur.execute(
                        "CREATE INDEX IF NOT EXISTS philthy_evidence_signals_date_idx "
                        "ON philthy_evidence_signals (event_date DESC, league, created_at DESC)"
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS philthy_evidence_manifests (
                            id BIGSERIAL PRIMARY KEY,
                            evidence_date DATE,
                            merkle_root TEXT,
                            payload JSONB,
                            created_at TIMESTAMPTZ DEFAULT NOW(),
                            UNIQUE (evidence_date, merkle_root)
                        )
                        """
                    )
                    for ddl in (
                        "ALTER TABLE philthy_evidence_manifests ADD COLUMN IF NOT EXISTS evidence_date DATE",
                        "ALTER TABLE philthy_evidence_manifests ADD COLUMN IF NOT EXISTS merkle_root TEXT",
                        "ALTER TABLE philthy_evidence_manifests ADD COLUMN IF NOT EXISTS payload JSONB",
                        "ALTER TABLE philthy_evidence_manifests ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()",
                    ):
                        cur.execute(ddl)
            _DB_READY = True
            _DB_ERROR_TYPE = None
            _log_storage_state("render_postgres")
            return True
        except Exception as exc:
            _mark_db_failed(exc)
            return False

def storage_status() -> dict[str, Any]:
    durable = _ensure_database()
    return {
        "mode": "render_postgres" if durable else "server_runtime_fallback",
        "durable": durable,
        "database_configured": bool(_database_url()),
        "database_error_type": _DB_ERROR_TYPE,
    }


def _safe_sha(value: Any) -> str | None:
    text = str(value or "").lower().strip()
    return text if len(text) == 64 and all(ch in "0123456789abcdef" for ch in text) else None


def _probability_for_selection(game: dict[str, Any], selection: str) -> float | None:
    ml = ((game.get("predictions") or {}).get("moneyline") or {})
    home_probability = ml.get("home_win_probability")
    if not isinstance(home_probability, (int, float)):
        home_probability = game.get("home_win_probability")
    if not isinstance(home_probability, (int, float)):
        home_probability = (game.get("market") or {}).get("home_probability")
    if not isinstance(home_probability, (int, float)):
        return None
    home_probability = float(home_probability)
    if not 0.0 <= home_probability <= 1.0:
        return None
    if selection == game.get("home"):
        return home_probability
    if selection == game.get("away"):
        return 1.0 - home_probability
    return None


def _signal_from_game(
    game: dict[str, Any],
    *,
    snapshot: datetime,
    data_latency_ms: int,
    engine_version: str,
) -> dict[str, Any] | None:
    event_id = str(game.get("event_id") or "").strip()
    sport = str(game.get("sport") or "").upper().strip()
    home = str(game.get("home") or "").strip()
    away = str(game.get("away") or "").strip()
    event_time_raw = game.get("event_time")
    predictions = game.get("predictions") or {}
    moneyline = predictions.get("moneyline") or {}
    selection = str(game.get("pick") or moneyline.get("pick") or "").strip()
    market = game.get("market") or {}
    price = market.get("moneyline_best_price")

    if not all((event_id, sport, home, away, event_time_raw, selection)):
        return None
    if not isinstance(price, (int, float)) or abs(float(price)) < 100:
        return None

    try:
        event_time = parse_utc(event_time_raw)
    except (TypeError, ValueError):
        return None
    if snapshot >= event_time:
        return None

    probability = _probability_for_selection(game, selection)
    if probability is None:
        return None

    probability_source = str(
        moneyline.get("source") or game.get("probability_source") or "unavailable"
    )
    model = game.get("model_metadata") or {}
    gate = model.get("promotion_gate") or {}
    gate_evidence = gate.get("evidence") or {}
    provenance = gate_evidence.get("provenance") or {}
    promoted = probability_source == "signed_promoted_trained_model" and gate.get("passed") is True
    market_fresh = market.get("freshness_verified") is True
    source_observed = market.get("moneyline_last_update") or market.get("last_update")

    if source_observed:
        try:
            if parse_utc(source_observed) > snapshot:
                return None
        except (TypeError, ValueError):
            return None

    model_family = str(
        model.get("model_type")
        or model.get("family")
        or ("governed_trained_model" if promoted else "market_baseline")
    )
    model_id = model.get("active_model_id") or model.get("model_id") or model.get("version")
    artifact_sha = _safe_sha(
        (gate.get("artifact_sha256") if isinstance(gate, dict) else None)
        or model.get("artifact_sha256")
        or model.get("sha256")
    )
    event_year = event_time.year
    deterministic_id = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"philthysports:{event_id}:moneyline:{snapshot.isoformat()}:{selection}",
    )

    return make_signal(
        match_id=event_id,
        league=sport,
        season=game.get("season") or str(event_year),
        home_team=home,
        away_team=away,
        snapshot_time_utc=snapshot,
        event_time_utc=event_time,
        data_latency_ms=data_latency_ms,
        market_type="moneyline",
        selection=selection,
        line=None,
        odds_decimal=decimal_from_american(price),
        raw_probability=probability,
        calibrated_probability=probability if promoted else None,
        engine_version=engine_version,
        model_family=model_family,
        reason_codes=reason_codes_for(
            probability_source,
            promoted=promoted,
            market_fresh=market_fresh,
        ),
        model_id=str(model_id) if model_id else None,
        model_artifact_sha256=artifact_sha,
        dataset_sha256=_safe_sha(provenance.get("dataset_sha256")),
        feature_schema_sha256=_safe_sha(provenance.get("feature_schema_sha256")),
        source=probability_source,
        source_observed_at_utc=source_observed,
        signal_id=str(deterministic_id),
    )


def _persist_batch(records: list[dict[str, Any]], snapshot: datetime) -> list[dict[str, Any]]:
    if not records:
        return []
    anchored, manifest = anchor_batch(records)
    day = snapshot.strftime("%Y-%m-%d")

    if _ensure_database():
        try:
            with psycopg.connect(_database_url(), autocommit=False, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    for row in anchored:
                        event_date = str(row.get("event_time_utc") or day)[:10]
                        cur.execute(
                            """
                            INSERT INTO philthy_evidence_signals
                                (signal_id, event_date, league, payload)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT (signal_id) DO NOTHING
                            """,
                            (row["signal_id"], event_date, row.get("league") or "", Jsonb(row)),
                        )
                    cur.execute(
                        """
                        INSERT INTO philthy_evidence_manifests
                            (evidence_date, merkle_root, payload)
                        VALUES (%s, %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (day, manifest.get("merkle_root"), Jsonb(manifest)),
                    )
                conn.commit()
            return anchored
        except Exception as exc:
            _mark_db_failed(exc)

    # Fail available: preserve the previous append-only runtime JSONL path. The
    # status endpoint explicitly reports that this fallback is not durable.
    with _LOCK:
        append_jsonl(SIGNAL_ROOT / day / "signals.jsonl", anchored)
        append_jsonl(SIGNAL_ROOT / day / "manifests.jsonl", [manifest])
    return anchored


def record_search_payload(payload: dict[str, Any], data_latency_ms: int) -> dict[str, Any]:
    games = payload.get("games")
    if not isinstance(games, list):
        return payload
    snapshot = datetime.now(timezone.utc)
    engine_version = str(
        payload.get("version")
        or payload.get("engine_version")
        or os.environ.get("PHILTHY_ENGINE_VERSION")
        or "philthy-v8"
    )

    candidates: list[tuple[int, dict[str, Any]]] = []
    for index, game in enumerate(games):
        if not isinstance(game, dict):
            continue
        try:
            signal = _signal_from_game(
                game,
                snapshot=snapshot,
                data_latency_ms=data_latency_ms,
                engine_version=engine_version,
            )
        except (ValueError, TypeError, OverflowError):
            signal = None
        if signal is not None:
            candidates.append((index, signal))

    anchored = _persist_batch([row for _, row in candidates], snapshot)
    for (index, _), signal in zip(candidates, anchored):
        games[index]["evidence"] = {
            "status": "RECORDED",
            "signal_id": signal["signal_id"],
            "record_sha256": signal["record_sha256"],
            "merkle_root": signal["merkle_root"],
            "merkle_leaf_index": signal["merkle_leaf_index"],
            "timestamp_utc": signal["timestamp_utc"],
            "data_latency_ms": signal["data_latency_ms"],
            "engine_version": signal["engine_version"],
            "schema_version": signal["schema_version"],
            "model_family": signal["model_family"],
            "reason_codes": signal["reason_codes"],
        }
    return payload


class SignalEvidenceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method != "GET" or request.url.path != "/v1/search":
            return await call_next(request)

        started = time.perf_counter_ns()
        response = await call_next(request)
        latency_ms = max(0, int((time.perf_counter_ns() - started) / 1_000_000))
        if response.status_code != 200:
            return response

        body = b"".join([chunk async for chunk in response.body_iterator])
        try:
            payload = json.loads(body.decode("utf-8"))
            if isinstance(payload, dict):
                payload = record_search_payload(payload, latency_ms)
                body = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
        except (UnicodeDecodeError, ValueError, TypeError):
            pass

        headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() not in {"content-length", "content-encoding"}
        }
        return Response(
            content=body,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type or "application/json",
            background=response.background,
        )


def _iter_signal_files() -> list[Path]:
    if not SIGNAL_ROOT.exists():
        return []
    return sorted(SIGNAL_ROOT.glob("*/signals.jsonl"), reverse=True)


def _read_signals(*, sport: str | None = None, date: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    wanted_sport = sport.upper() if sport else None
    if _ensure_database():
        try:
            clauses: list[str] = []
            params: list[Any] = []
            if wanted_sport:
                clauses.append("league = %s")
                params.append(wanted_sport)
            if date:
                clauses.append("event_date = %s")
                params.append(date)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            params.append(int(limit))
            query = (
                "SELECT payload FROM philthy_evidence_signals"
                + where
                + " ORDER BY created_at DESC LIMIT %s"
            )
            with psycopg.connect(_database_url(), autocommit=True, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    values = cur.fetchall()
            return [value[0] if isinstance(value[0], dict) else json.loads(value[0]) for value in values]
        except Exception as exc:
            _mark_db_failed(exc)

    rows: list[dict[str, Any]] = []
    for path in _iter_signal_files():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if wanted_sport and row.get("league") != wanted_sport:
                continue
            if date and not str(row.get("event_time_utc") or "").startswith(date):
                continue
            rows.append(row)
            if len(rows) >= limit:
                return rows
    return rows


def _find_signal(signal_id: str) -> dict[str, Any] | None:
    for row in _read_signals(limit=10000):
        if row.get("signal_id") == signal_id:
            return row
    return None


@router.get("/signals")
def list_signals(
    sport: str | None = Query(default=None, pattern="^(NFL|NBA|MLB|NHL)$"),
    date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    limit: int = Query(default=100, ge=1, le=1000),
):
    rows = _read_signals(sport=sport, date=date, limit=limit)
    storage = storage_status()
    return {
        "schema_version": "2",
        "signals": rows,
        "count": len(rows),
        "append_only_runtime_log": True,
        "storage_root": storage["mode"],
        "durable_storage": storage["durable"],
        "storage_status": storage,
    }


@router.get("/signals/{signal_id}")
def get_signal(signal_id: str):
    row = _find_signal(signal_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Signal evidence not found")
    return row


@router.get("/verify/{signal_id}")
def verify_signal_endpoint(signal_id: str):
    row = _find_signal(signal_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Signal evidence not found")
    root = row.get("merkle_root")
    proof = row.get("merkle_proof") or []
    record_hash_valid = verify_signal(row)
    merkle_valid = bool(root) and verify_merkle_proof(row["record_sha256"], proof, root)
    chronology_valid = parse_utc(row["snapshot_time_utc"]) < parse_utc(row["event_time_utc"])
    return {
        "signal_id": signal_id,
        "record_hash_valid": record_hash_valid,
        "merkle_proof_valid": merkle_valid,
        "chronology_valid": chronology_valid,
        "verified": record_hash_valid and merkle_valid and chronology_valid,
        "record_sha256": row.get("record_sha256"),
        "merkle_root": root,
    }


@router.get("/roots/{date}")
def roots_for_date(date: str):
    if _ensure_database():
        try:
            with psycopg.connect(_database_url(), autocommit=True, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT payload FROM philthy_evidence_manifests "
                        "WHERE evidence_date = %s ORDER BY created_at ASC",
                        (date,),
                    )
                    values = cur.fetchall()
            roots = [value[0] if isinstance(value[0], dict) else json.loads(value[0]) for value in values]
            return {
                "date": date,
                "roots": roots,
                "count": len(roots),
                "storage_root": "render_postgres",
                "durable_storage": True,
            }
        except Exception as exc:
            _mark_db_failed(exc)

    path = SIGNAL_ROOT / date / "manifests.jsonl"
    if not path.exists():
        return {
            "date": date,
            "roots": [],
            "count": 0,
            "storage_root": "server_runtime_fallback",
            "durable_storage": False,
        }
    roots: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                roots.append(json.loads(line))
            except ValueError:
                continue
    return {
        "date": date,
        "roots": roots,
        "count": len(roots),
        "storage_root": "server_runtime_fallback",
        "durable_storage": False,
    }
