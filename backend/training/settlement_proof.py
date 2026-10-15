from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from evidence_pipeline import ESPN, _canonical, _json, _sha256


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _espn(sport: str, game_date: date) -> dict[str, dict[str, Any]]:
    category, league = ESPN[sport]
    raw = _json(f"https://site.api.espn.com/apis/site/v2/sports/{category}/{league}/scoreboard?dates={game_date:%Y%m%d}")
    out: dict[str, dict[str, Any]] = {}
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
            hs, aw = float(home.get("score")), float(away.get("score"))
        except (TypeError, ValueError):
            continue
        if hs == aw:
            continue
        event_id = str(event.get("id") or "")
        if event_id:
            out[event_id] = {
                "target_home_win": int(hs > aw),
                "final_home_score": hs,
                "final_away_score": aw,
                "settlement_source": "ESPN scoreboard",
                "settlement_source_event_id": event_id,
                "settlement_payload_sha256": _hash(event),
            }
    return out


def _mlb(game_date: date) -> dict[str, dict[str, Any]]:
    raw = _json(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={game_date.isoformat()}")
    out: dict[str, dict[str, Any]] = {}
    for day in raw.get("dates") or []:
        for game in day.get("games") or []:
            if (game.get("status") or {}).get("abstractGameState") != "Final":
                continue
            home, away = (game.get("teams") or {}).get("home") or {}, (game.get("teams") or {}).get("away") or {}
            try:
                hs, aw = float(home.get("score")), float(away.get("score"))
            except (TypeError, ValueError):
                continue
            if hs == aw:
                continue
            event_id = str(game.get("gamePk") or "")
            if event_id:
                out[event_id] = {
                    "target_home_win": int(hs > aw),
                    "final_home_score": hs,
                    "final_away_score": aw,
                    "settlement_source": "MLB Stats API",
                    "settlement_source_event_id": event_id,
                    "settlement_payload_sha256": _hash(game),
                }
    return out


def _nhl(game_date: date) -> dict[str, dict[str, Any]]:
    raw = _json(f"https://api-web.nhle.com/v1/schedule/{game_date.isoformat()}")
    out: dict[str, dict[str, Any]] = {}
    for day in raw.get("gameWeek") or []:
        if day.get("date") != game_date.isoformat():
            continue
        for game in day.get("games") or []:
            if str(game.get("gameState") or "").upper() not in {"OFF", "FINAL"}:
                continue
            home, away = game.get("homeTeam") or {}, game.get("awayTeam") or {}
            try:
                hs, aw = float(home.get("score")), float(away.get("score"))
            except (TypeError, ValueError):
                continue
            if hs == aw:
                continue
            event_id = str(game.get("id") or "")
            if event_id:
                out[event_id] = {
                    "target_home_win": int(hs > aw),
                    "final_home_score": hs,
                    "final_away_score": aw,
                    "settlement_source": "NHL Web API",
                    "settlement_source_event_id": event_id,
                    "settlement_payload_sha256": _hash(game),
                }
    return out


def reconcile(root: Path, lookback_days: int = 21) -> dict[str, Any]:
    labels_path = root / "settled" / "labels.jsonl"
    if not labels_path.exists():
        return {"proofs": 0, "status": "NO_LABELS"}
    labels = [json.loads(x) for x in labels_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    proof_path = root / "settled" / "settlement_proofs.jsonl"
    proofs: dict[tuple[str, str], dict[str, Any]] = {}
    if proof_path.exists():
        for line in proof_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                proofs[(item["sport"], item["event_id"])] = item

    today = datetime.now(timezone.utc).date()
    requested: dict[tuple[str, date], set[str]] = {}
    for label in labels:
        try:
            game_date = date.fromisoformat(str(label["event_date"]))
        except Exception:
            continue
        if today - timedelta(days=lookback_days) <= game_date <= today and (label["sport"], label["event_id"]) not in proofs:
            requested.setdefault((label["sport"], game_date), set()).add(label["event_id"])

    cache: dict[tuple[str, date], dict[str, dict[str, Any]]] = {}
    for sport, game_date in sorted(requested, key=lambda item: (item[1], item[0])):
        try:
            cache[(sport, game_date)] = _espn(sport, game_date) if sport in ESPN else _mlb(game_date) if sport == "MLB" else _nhl(game_date) if sport == "NHL" else {}
        except Exception:
            cache[(sport, game_date)] = {}

    now = datetime.now(timezone.utc).isoformat()
    for label in labels:
        key = (label.get("sport"), label.get("event_id"))
        if key in proofs:
            continue
        try:
            game_date = date.fromisoformat(str(label["event_date"]))
        except Exception:
            continue
        found = cache.get((key[0], game_date), {}).get(key[1])
        if not found or int(found["target_home_win"]) != int(label.get("target_home_win")):
            continue
        proof = {
            "schema_version": 1,
            "sport": key[0],
            "event_id": key[1],
            "event_date": game_date.isoformat(),
            "settlement_status": "SETTLED_FINAL",
            "settlement_observed_at": now,
            "label_first_observed_at": label.get("settled_at"),
            **found,
        }
        proof["proof_sha256"] = _hash(proof)
        proofs[key] = proof

    proof_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = proof_path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for item in sorted(proofs.values(), key=lambda x: (x["sport"], x["event_date"], x["event_id"])):
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    tmp.replace(proof_path)
    return {"proofs": len(proofs), "sha256": _sha256(proof_path), "status": "PASS"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture independent official-result settlement proofs")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--lookback-days", type=int, default=21)
    args = parser.parse_args()
    print(json.dumps(reconcile(args.root, args.lookback_days), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
