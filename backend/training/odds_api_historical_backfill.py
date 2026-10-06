from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

SPORT_KEYS = {
    "NBA": "basketball_nba",
    "MLB": "baseball_mlb",
    "NHL": "icehockey_nhl",
    "NFL": "americanfootball_nfl",
}
BASE = "https://api.the-odds-api.com/v4/historical/sports"


@dataclass(frozen=True)
class SnapshotRequest:
    sport: str
    snapshot_at: datetime

    @property
    def key(self) -> str:
        return f"{self.sport}-{self.snapshot_at.strftime('%Y%m%dT%H%M%SZ')}"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def iter_dates(start: date, end: date) -> Iterable[date]:
    if end < start:
        raise ValueError("end date must be on or after start date")
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def build_plan(sports: list[str], start: date, end: date, hour_utc: int) -> list[SnapshotRequest]:
    if not 0 <= hour_utc <= 23:
        raise ValueError("hour_utc must be 0..23")
    plan: list[SnapshotRequest] = []
    for day in iter_dates(start, end):
        stamp = datetime.combine(day, time(hour=hour_utc), tzinfo=timezone.utc)
        for sport in sports:
            plan.append(SnapshotRequest(sport=sport, snapshot_at=stamp))
    return plan


def estimate_credits(plan: list[SnapshotRequest], *, markets: int = 1, regions: int = 1) -> int:
    # Official historical featured-market pricing: 10 credits per region x market.
    return len(plan) * 10 * markets * regions


def _safe_usage(response: requests.Response) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    for header, key in (
        ("x-requests-remaining", "remaining"),
        ("x-requests-used", "used"),
        ("x-requests-last", "last"),
    ):
        raw = response.headers.get(header)
        try:
            out[key] = int(raw) if raw is not None else None
        except ValueError:
            out[key] = None
    return out


def fetch_snapshot(req: SnapshotRequest, api_key: str, output_dir: Path) -> dict[str, Any]:
    sport_key = SPORT_KEYS[req.sport]
    response = requests.get(
        f"{BASE}/{sport_key}/odds",
        params={
            "apiKey": api_key,
            "regions": "us",
            "markets": "h2h",
            "oddsFormat": "decimal",
            "dateFormat": "iso",
            "date": _iso(req.snapshot_at),
        },
        headers={"Accept": "application/json", "User-Agent": "PhilthySports/historical-backfill"},
        timeout=30,
    )
    usage = _safe_usage(response)
    if response.status_code != 200:
        return {
            "request": req.key,
            "sport": req.sport,
            "requested_snapshot": _iso(req.snapshot_at),
            "http_status": response.status_code,
            "usage": usage,
            "status": "FAILED",
        }

    raw = response.content
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise RuntimeError(f"{req.key}: invalid historical response schema")
    timestamp = payload.get("timestamp")
    if not isinstance(timestamp, str):
        raise RuntimeError(f"{req.key}: historical response missing provider timestamp")

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / f"{req.key}.json"
    raw_path.write_bytes(raw)
    manifest = {
        "schema_version": 1,
        "sport": req.sport,
        "sport_key": sport_key,
        "requested_snapshot": _iso(req.snapshot_at),
        "provider_snapshot": timestamp,
        "raw_file": raw_path.name,
        "raw_sha256": _sha256_bytes(raw),
        "events": len(payload["data"]),
        "usage": usage,
        "credential_embedded": False,
        "promotion_ready": False,
        "promotion_eligible": False,
        "label_join_required": True,
        "admissibility_rule": "provider snapshot timestamp must be before event start; authoritative final-result publication evidence must be joined separately",
    }
    (output_dir / f"{req.key}.manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return {**manifest, "status": "CAPTURED_PREGAME_EVIDENCE"}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Capture The Odds API historical h2h snapshots into an immutable evidence inbox. "
            "This collector never fabricates or infers settled labels and never promotes data by itself."
        )
    )
    parser.add_argument("command", choices=["plan", "fetch"])
    parser.add_argument("--sports", default="NBA,MLB,NHL")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--hour-utc", type=int, default=12)
    parser.add_argument("--max-credits", type=int, default=0,
                        help="Hard request budget. Fetch refuses to run when estimate exceeds this value.")
    parser.add_argument("--output-dir", type=Path, default=Path("evidence/historical/inbox/the-odds-api"))
    args = parser.parse_args()

    sports = [x.strip().upper() for x in args.sports.split(",") if x.strip()]
    invalid = [x for x in sports if x not in SPORT_KEYS]
    if invalid:
        raise SystemExit(f"unsupported sports: {invalid}")
    plan = build_plan(
        sports,
        date.fromisoformat(args.start),
        date.fromisoformat(args.end),
        args.hour_utc,
    )
    estimate = estimate_credits(plan)
    summary = {
        "schema_version": 1,
        "sports": sports,
        "start": args.start,
        "end": args.end,
        "hour_utc": args.hour_utc,
        "snapshot_requests": len(plan),
        "estimated_credits": estimate,
        "markets": ["h2h"],
        "regions": ["us"],
        "note": "estimate uses 10 historical credits per one-region, one-market snapshot request",
    }
    if args.command == "plan":
        print(json.dumps(summary, indent=2, sort_keys=True))
        return

    if args.max_credits <= 0:
        raise SystemExit("fetch requires an explicit positive --max-credits hard budget")
    if estimate > args.max_credits:
        raise SystemExit(
            f"refusing historical fetch: estimated {estimate} credits exceeds --max-credits {args.max_credits}"
        )
    if os.getenv("CREDENTIAL_ROTATION_CONFIRMED", "").strip().lower() != "true":
        raise SystemExit("refusing historical fetch: credential rotation is not confirmed")
    key = os.getenv("ODDS_API_KEY", "").strip()
    if not key:
        raise SystemExit("refusing historical fetch: ODDS_API_KEY is not configured")

    results: list[dict[str, Any]] = []
    for req in plan:
        result = fetch_snapshot(req, key, args.output_dir)
        results.append(result)
        usage = result.get("usage") or {}
        remaining = usage.get("remaining")
        if isinstance(remaining, int) and remaining < 10:
            break
        if result.get("status") == "FAILED":
            # Fail closed on auth/plan/quota/server errors rather than burning budget.
            break

    report = {
        **summary,
        "attempted": len(results),
        "captured": sum(r.get("status") == "CAPTURED_PREGAME_EVIDENCE" for r in results),
        "results": results,
        "secret_exposed": False,
        "promotion_ready": False,
        "label_join_required": True,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "capture-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if any(r.get("status") == "FAILED" for r in results):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
