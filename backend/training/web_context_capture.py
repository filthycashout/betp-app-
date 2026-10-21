from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sports_web_research import research_event


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def capture(
    *,
    sport: str,
    event_id: str,
    event_time: str,
    home_team: str,
    away_team: str,
    topic: str,
    output_dir: Path,
) -> dict[str, Any]:
    event_dt = _utc(event_time)
    started = datetime.now(timezone.utc)
    if started >= event_dt:
        raise ValueError("web-context capture must occur before event_time")
    result = research_event(
        sport,
        home_team,
        away_team,
        event_time=event_dt.isoformat(),
        topic=topic,
    )
    if result.get("status") != "OK":
        return {
            "status": str(result.get("status") or "UNAVAILABLE"),
            "sport": sport.upper(),
            "event_id": event_id,
            "event_time": event_dt.isoformat(),
            "topic": topic,
            "captured": False,
            "detail": result,
        }

    captured_at = datetime.now(timezone.utc)
    if captured_at >= event_dt:
        raise ValueError("web-context response arrived after event start; capture rejected")

    output_dir.mkdir(parents=True, exist_ok=True)
    safe_event = "".join(ch for ch in str(event_id) if ch.isalnum() or ch in {"-", "_"})[:128]
    if not safe_event:
        raise ValueError("event_id has no safe characters")
    stamp = captured_at.strftime("%Y%m%dT%H%M%SZ")
    raw_path = output_dir / f"web_context_{sport.lower()}_{safe_event}_{topic}_{stamp}.json"
    raw_doc = {
        "sport": sport.upper(),
        "event_id": str(event_id),
        "event_time": event_dt.isoformat(),
        "captured_at": captured_at.isoformat(),
        "home_team": home_team,
        "away_team": away_team,
        "topic": topic,
        "research": result,
    }
    raw_path.write_bytes(_canonical(raw_doc))
    manifest = {
        "schema_version": "web-context-sidecar-v1",
        "sport": sport.upper(),
        "event_id": str(event_id),
        "event_time": event_dt.isoformat(),
        "snapshot_time": captured_at.isoformat(),
        "topic": topic,
        "source": "ScrapeGraphAI V2 public-web research",
        "raw_file": raw_path.name,
        "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        "chronology_rule": "snapshot_time < event_time",
        "trusted_for_instructions": False,
        "used_in_prediction": False,
        "historical_training_eligible": False,
        "promotion_eligible": False,
        "canonical_admission_required": True,
        "admission_note": (
            "This sidecar may inform review or later feature reconstruction. It cannot enter training "
            "until a separately versioned numeric feature with observed_at provenance passes canonical admission."
        ),
    }
    manifest_path = raw_path.with_name(raw_path.stem + "_manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "OK", "raw_path": str(raw_path), "manifest_path": str(manifest_path), **manifest}


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture pregame ScrapeGraphAI evidence as a non-model sidecar")
    parser.add_argument("--sport", required=True, choices=["NFL", "NBA", "MLB", "NHL"])
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--event-time", required=True)
    parser.add_argument("--home-team", required=True)
    parser.add_argument("--away-team", required=True)
    parser.add_argument("--topic", choices=["availability", "roles"], default="availability")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(capture(
        sport=args.sport,
        event_id=args.event_id,
        event_time=args.event_time,
        home_team=args.home_team,
        away_team=args.away_team,
        topic=args.topic,
        output_dir=args.output_dir,
    ), indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
