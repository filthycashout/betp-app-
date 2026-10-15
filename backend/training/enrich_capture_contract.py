from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def enrich(directory: Path) -> dict[str, Any]:
    changed = []
    for manifest_path in sorted(directory.glob("manifest_*.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        raw_path = directory / manifest["raw_file"]["name"]
        rows_path = directory / manifest["rows_file"]["name"]
        if _sha256(raw_path) != manifest["raw_file"]["sha256"] or _sha256(rows_path) != manifest["rows_file"]["sha256"]:
            raise ValueError(f"pre-enrichment checksum mismatch: {manifest_path.name}")

        raw_doc = json.loads(raw_path.read_text(encoding="utf-8"))
        games = {
            (str(game.get("sport") or "").upper(), str(game.get("event_id") or "")): game
            for game in (raw_doc.get("payload") or {}).get("games") or []
        }
        rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        raw_sha = _sha256(raw_path)
        output = []
        for row in rows:
            game = games.get((str(row.get("sport") or "").upper(), str(row.get("event_id") or ""))) or {}
            market = game.get("market") or {}
            home = str(row.get("home_team") or "")

            # Prefer the canonical current runtime shape. Keep compatibility with
            # older moneyline_best_* fields, but never synthesize a quote/book.
            price = market.get("home_ml")
            book = market.get("home_best_book")
            if price is None or not book:
                pick = str(market.get("moneyline_pick") or "")
                if pick and home and pick.casefold() == home.casefold():
                    price = market.get("moneyline_best_price")
                    book = market.get("moneyline_best_book")

            row.update(
                {
                    "schema_version": "2",
                    "provider_event_id": game.get("provider_event_id") or game.get("odds_event_id"),
                    "provider_market_id": market.get("provider_market_id") or market.get("market_id"),
                    "market_type": "moneyline" if row.get("market_home_probability") is not None else None,
                    "selection": home if row.get("market_home_probability") is not None else None,
                    "line": None,
                    "american_price": price,
                    "book": book,
                    "provider": game.get("market_source") or game.get("schedule_source"),
                    "event_started_at": row.get("event_time"),
                    "quote_captured_at": row.get("as_of"),
                    "raw_snapshot_sha256": raw_sha,
                }
            )
            output.append(row)

        with rows_path.open("w", encoding="utf-8") as handle:
            for row in output:
                handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")

        manifest["schema_version"] = 2
        manifest["data_contract_version"] = "2"
        manifest["rows_file"]["sha256"] = _sha256(rows_path)
        manifest["rows_file"]["bytes"] = rows_path.stat().st_size
        manifest["market_identity_policy"] = "preserve provider identifiers when supplied; never synthesize missing provider market IDs"
        manifest["chronology_rule"] = "quote_captured_at/as_of < event_started_at/event_time"
        manifest_path.write_bytes(_canonical(manifest))
        changed.append({"manifest": manifest_path.name, "rows": len(output), "rows_sha256": manifest["rows_file"]["sha256"]})
    return {"status": "PASS", "captures": changed}


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich strict pregame capture with evidence contract v2 metadata")
    parser.add_argument("--capture-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(enrich(args.capture_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
