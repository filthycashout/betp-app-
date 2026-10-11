#!/usr/bin/env python3
"""Single CLI entrypoint for the unified PhilthyParleys sports_ai engine."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sports_ai import SUPPORTED_SPORTS
from sports_ai.orchestrator import MarketCandidate, SportsAIEngine


def _candidate(row: dict[str, Any], sport: str | None = None) -> MarketCandidate:
    payload = dict(row)
    if sport is not None:
        payload.setdefault("sport", sport)
    return MarketCandidate(**payload)


def run_sport(sport: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = sport.upper()
    if normalized not in SUPPORTED_SPORTS:
        raise ValueError(f"unsupported sport: {sport}")
    candidates = [_candidate(row, normalized) for row in rows]
    return SportsAIEngine().run_sport(normalized, candidates)


def run_all(rows_by_sport: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    engine = SportsAIEngine()
    candidates = {
        sport: [_candidate(row, sport) for row in rows_by_sport.get(sport, [])]
        for sport in SUPPORTED_SPORTS
    }
    return engine.run_all(candidates)


def _load_input(path: str) -> Any:
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the unified PhilthyParleys sports_ai engine")
    parser.add_argument("--sport", choices=SUPPORTED_SPORTS)
    parser.add_argument("--live", action="store_true", help="Use the existing governed live backend providers")
    parser.add_argument("--date", help="Local game date as YYYY-MM-DD for --live")
    parser.add_argument("--query", default="", help="Optional team/matchup filter for --live")
    parser.add_argument(
        "--input",
        default="-",
        help="Offline JSON candidate file; '-' reads stdin. Ignored with --live.",
    )
    args = parser.parse_args(argv)

    if args.live:
        from sports_ai.live import run_live_all, run_live_sport

        result = (
            run_live_sport(args.sport, date=args.date, query=args.query)
            if args.sport
            else run_live_all(date=args.date, query=args.query)
        )
    else:
        payload = _load_input(args.input)
        if args.sport:
            if isinstance(payload, dict) and args.sport in payload:
                payload = payload[args.sport]
            if not isinstance(payload, list):
                parser.error("--sport input must be a JSON list (or a mapping containing that sport)")
            result = run_sport(args.sport, payload)
        else:
            if not isinstance(payload, dict):
                parser.error("run_all input must be a JSON object keyed by MLB/NHL/NBA/NFL")
            unknown = sorted(set(payload) - set(SUPPORTED_SPORTS))
            if unknown:
                parser.error(f"unsupported sport keys: {', '.join(unknown)}")
            result = run_all(payload)

    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
