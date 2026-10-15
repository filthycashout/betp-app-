from __future__ import annotations

import argparse
import json
import math
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .evidence_pipeline import (
        PRODUCTION_BASE_URL,
        SPORTS,
        _canonical,
        _json,
        _parse_time,
        _sha256,
        normalize_base_url,
    )
except ImportError:  # pragma: no cover - supports direct script execution
    from evidence_pipeline import (  # type: ignore
        PRODUCTION_BASE_URL,
        SPORTS,
        _canonical,
        _json,
        _parse_time,
        _sha256,
        normalize_base_url,
    )


def _probability(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and 0.0 < number < 1.0 else None


def normalized_prop_rows(payload: dict[str, Any], fetched_at: datetime) -> list[dict[str, Any]]:
    """Convert runtime-validated prop quotes into immutable research-only rows."""

    rows: list[dict[str, Any]] = []
    for game in payload.get("games") or []:
        sport = str(game.get("sport") or "").upper()
        event_id = str(game.get("event_id") or "").strip()
        if sport not in SPORTS or not event_id:
            continue
        try:
            event_time = _parse_time(str(game.get("event_time") or ""))
        except Exception:
            continue
        if fetched_at >= event_time:
            continue

        for prop in game.get("props_to_watch") or []:
            player = str(prop.get("player") or "").strip()
            market = str(prop.get("market") or "").strip()
            if not player or not market:
                continue
            probability = _probability(prop.get("market_probability"))
            quote_time = prop.get("best_price_last_update") or prop.get("last_update")
            if quote_time:
                try:
                    quote_time = _parse_time(str(quote_time)).isoformat()
                except Exception:
                    quote_time = None

            rows.append(
                {
                    "sport": sport,
                    "event_id": event_id,
                    "event_time": event_time.isoformat(),
                    "as_of": fetched_at.isoformat(),
                    "home_team": game.get("home"),
                    "away_team": game.get("away"),
                    "player": player,
                    "market": market,
                    "line": prop.get("line"),
                    "market_side": prop.get("recommended_side") or prop.get("outcome"),
                    "market_probability": probability,
                    "probability_method": prop.get("probability_method"),
                    "best_available_price": prop.get("best_available_price"),
                    "best_available_book": prop.get("best_available_book"),
                    "quote_last_update": quote_time,
                    "contributing_books": prop.get("contributing_books") or [],
                    "book_count": prop.get("book_count"),
                    "freshness_basis": prop.get("freshness_basis") or [],
                    "provider_timestamp_verified": bool(prop.get("provider_timestamp_verified")),
                    "observed_at_verified": bool(prop.get("observed_at_verified")),
                    "runtime_model_state": prop.get("model_state"),
                    "evidence_role": "MARKET_SNAPSHOT_ONLY",
                    "model_probability": None,
                    "model_edge": None,
                    "model_ev": None,
                    "promotion_eligible": False,
                    "automatic_wagering": False,
                }
            )

    rows.sort(
        key=lambda row: (
            row["sport"],
            row["event_time"],
            row["event_id"],
            row["player"],
            row["market"],
            str(row["line"]),
        )
    )
    return rows


def capture_props(
    base_url: str,
    output_dir: Path,
    *,
    days: int = 1,
    props_limit: int = 20,
) -> dict[str, Any]:
    """Capture current prop evidence without treating market leans as model picks.

    This command is intentionally manual. It does not schedule itself, place wagers,
    or promote any research distribution. Provider usage therefore occurs only when
    an operator explicitly invokes it.
    """

    if not 1 <= days <= 7:
        raise ValueError("days must be between 1 and 7")
    if not 1 <= props_limit <= 20:
        raise ValueError("props_limit must be between 1 and 20")

    base_url = normalize_base_url(base_url)
    query = urllib.parse.urlencode(
        {"include_props": "true", "props_limit": str(props_limit), "days": str(days)}
    )
    source_url = f"{base_url}/v1/today?{query}"
    payload = _json(source_url)
    fetched_at = datetime.now(timezone.utc)
    rows = normalized_prop_rows(payload, fetched_at)

    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = fetched_at.strftime("%Y%m%dT%H%M%SZ")
    raw_path = output_dir / f"props_raw_{stamp}.json"
    rows_path = output_dir / f"props_{stamp}.jsonl"
    manifest_path = output_dir / f"props_manifest_{stamp}.json"

    raw_path.write_bytes(
        _canonical(
            {
                "fetched_at": fetched_at.isoformat(),
                "source_url": source_url,
                "payload": payload,
            }
        )
    )
    with rows_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")

    manifest = {
        "schema_version": 1,
        "capture_type": "strict_pregame_player_prop_market_snapshot",
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
        "promotion_eligible": False,
        "automatic_wagering": False,
        "secrets_embedded": False,
        "note": (
            "Market evidence only. A separate settled prop corpus plus chronological "
            "OOF calibration and strict promotion gates are required before any model probability is eligible."
        ),
    }
    manifest_path.write_bytes(_canonical(manifest))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture governed PhilthyParleys pregame player-prop market evidence"
    )
    parser.add_argument("--base-url", default=PRODUCTION_BASE_URL)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--props-limit", type=int, default=20)
    args = parser.parse_args()
    manifest = capture_props(
        args.base_url,
        args.output_dir,
        days=args.days,
        props_limit=args.props_limit,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
