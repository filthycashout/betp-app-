from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

API_BASE = "https://api.the-odds-api.com"
SPORT_KEYS = {
    "NFL": "americanfootball_nfl",
    "NBA": "basketball_nba",
    "MLB": "baseball_mlb",
    "NHL": "icehockey_nhl",
}
RETRYABLE = {429, 502, 503, 504}
FEATURED_MARKETS = ("h2h", "spreads", "totals")
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class BackfillBlocked(RuntimeError):
    pass


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def estimated_credits(markets: list[str], regions: list[str], requests_count: int = 1) -> int:
    # Historical featured and historical event-odds endpoints are documented at
    # 10 credits per returned market per region. This is a conservative request
    # plan; empty/unavailable markets may cost less.
    return 10 * max(1, len(set(markets))) * max(1, len(set(regions))) * max(1, requests_count)


def _enabled() -> bool:
    return os.getenv("ODDS_HISTORICAL_BACKFILL_ENABLED", "false").lower() == "true"


def _api_key() -> str:
    value = os.getenv("ODDS_API_KEY", "").strip() or os.getenv("ODDS_API_NET_KEY", "").strip()
    if not value:
        raise BackfillBlocked("ODDS_API_KEY/ODDS_API_NET_KEY is not configured")
    return value


def _get(path: str, params: dict[str, str]) -> tuple[dict[str, Any], dict[str, str]]:
    if not path.startswith("/v4/historical/sports/"):
        raise ValueError("historical backfill may only call the documented historical sports namespace")
    api_key = _api_key()
    safe_params = dict(params)
    safe_params["apiKey"] = api_key
    last_status: int | None = None
    for attempt in range(3):
        response = requests.get(
            API_BASE + path,
            params=safe_params,
            headers={"Accept": "application/json", "User-Agent": "PhilthySports-HistoricalMarket/1.0"},
            timeout=(5, 45),
            allow_redirects=False,
        )
        last_status = response.status_code
        if response.is_redirect:
            response.close()
            raise BackfillBlocked("Odds API redirect refused")
        if response.status_code in RETRYABLE and attempt < 2:
            response.close()
            time.sleep(attempt + 1)
            continue
        if response.status_code != 200:
            text = response.text[:200]
            response.close()
            raise BackfillBlocked(f"Odds API HTTP {last_status}: {text}")
        if len(response.content) > MAX_RESPONSE_BYTES:
            response.close()
            raise BackfillBlocked("Odds API response exceeds configured safety limit")
        payload = response.json()
        headers = {
            "x-requests-remaining": response.headers.get("x-requests-remaining", ""),
            "x-requests-used": response.headers.get("x-requests-used", ""),
            "x-requests-last": response.headers.get("x-requests-last", ""),
        }
        response.close()
        if not isinstance(payload, dict):
            raise BackfillBlocked("historical response must be an object wrapper")
        return payload, headers
    raise BackfillBlocked(f"Odds API unavailable after retries (last HTTP {last_status})")


def _decimal_probability(price: Any) -> float | None:
    try:
        decimal = float(price)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(decimal) or decimal <= 1.0:
        return None
    return 1.0 / decimal


def _devig_two_way(outcomes: list[dict[str, Any]], home: str, away: str) -> float | None:
    values: dict[str, float] = {}
    for outcome in outcomes:
        name = str(outcome.get("name") or "")
        p = _decimal_probability(outcome.get("price"))
        if p is not None and name in {home, away}:
            values[name] = p
    if set(values) != {home, away}:
        return None
    total = values[home] + values[away]
    if total <= 0:
        return None
    return values[home] / total


def _market(bookmaker: dict[str, Any], key: str) -> dict[str, Any] | None:
    for market in bookmaker.get("markets") or []:
        if market.get("key") == key:
            return market
    return None


def normalize_featured(snapshot: dict[str, Any], requested_at: datetime, sport: str) -> list[dict[str, Any]]:
    observed = snapshot.get("timestamp")
    try:
        observed_at = _utc(observed) if observed else requested_at
    except Exception:
        observed_at = requested_at
    rows: list[dict[str, Any]] = []
    for event in snapshot.get("data") or []:
        home = str(event.get("home_team") or "").strip()
        away = str(event.get("away_team") or "").strip()
        event_id = str(event.get("id") or "").strip()
        try:
            event_time = _utc(event.get("commence_time"))
        except Exception:
            continue
        if not home or not away or not event_id or observed_at >= event_time:
            continue
        home_probs: list[float] = []
        home_spreads: list[float] = []
        totals: list[float] = []
        bookmaker_times: list[str] = []
        for bookmaker in event.get("bookmakers") or []:
            h2h = _market(bookmaker, "h2h")
            if h2h:
                probability = _devig_two_way(h2h.get("outcomes") or [], home, away)
                if probability is not None:
                    home_probs.append(probability)
            spread = _market(bookmaker, "spreads")
            if spread:
                for outcome in spread.get("outcomes") or []:
                    if outcome.get("name") == home:
                        try:
                            point = float(outcome.get("point"))
                            if math.isfinite(point):
                                home_spreads.append(point)
                        except (TypeError, ValueError):
                            pass
            total_market = _market(bookmaker, "totals")
            if total_market:
                points = []
                for outcome in total_market.get("outcomes") or []:
                    try:
                        point = float(outcome.get("point"))
                        if math.isfinite(point):
                            points.append(point)
                    except (TypeError, ValueError):
                        pass
                if points:
                    totals.append(statistics.median(points))
            if bookmaker.get("last_update"):
                bookmaker_times.append(str(bookmaker["last_update"]))
        if not home_probs:
            continue
        rows.append(
            {
                "sport": sport,
                "provider_event_id": event_id,
                "event_time": event_time.isoformat(),
                "snapshot_time": observed_at.isoformat(),
                "home_team": home,
                "away_team": away,
                "consensus_de_vig_home_probability": statistics.mean(home_probs),
                "home_spread": statistics.median(home_spreads) if home_spreads else None,
                "consensus_total": statistics.median(totals) if totals else None,
                "bookmaker_count_h2h": len(home_probs),
                "latest_bookmaker_update": max(bookmaker_times) if bookmaker_times else None,
                "source": "The Odds API historical odds",
                "promotion_eligible": False,
                "canonical_admission_required": True,
            }
        )
    rows.sort(key=lambda row: (row["event_time"], row["provider_event_id"]))
    return rows


def fetch_featured_snapshot(
    sport: str,
    snapshot_time: str,
    *,
    regions: list[str],
    markets: list[str],
    execute: bool,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    sport = sport.upper().strip()
    if sport not in SPORT_KEYS:
        raise ValueError("sport must be NFL, NBA, MLB or NHL")
    requested_at = _utc(snapshot_time)
    markets = [m for m in markets if m in FEATURED_MARKETS]
    if not markets:
        raise ValueError("at least one featured market is required")
    regions = [r.strip() for r in regions if r.strip()]
    if not regions:
        raise ValueError("at least one region is required")
    plan = {
        "sport": sport,
        "snapshot_time": requested_at.isoformat(),
        "regions": regions,
        "markets": markets,
        "estimated_max_credits": estimated_credits(markets, regions),
        "paid_historical_endpoint": True,
        "execution_requested": bool(execute),
        "execution_enabled": _enabled(),
        "api_key_configured": bool(os.getenv("ODDS_API_KEY", "").strip() or os.getenv("ODDS_API_NET_KEY", "").strip()),
    }
    if not execute:
        return {"status": "DRY_RUN", "plan": plan}
    if not _enabled():
        raise BackfillBlocked("set ODDS_HISTORICAL_BACKFILL_ENABLED=true to acknowledge paid historical usage")

    path = f"/v4/historical/sports/{SPORT_KEYS[sport]}/odds"
    payload, quota_headers = _get(
        path,
        {
            "regions": ",".join(regions),
            "markets": ",".join(markets),
            "date": requested_at.isoformat().replace("+00:00", "Z"),
            "dateFormat": "iso",
            "oddsFormat": "decimal",
        },
    )
    rows = normalize_featured(payload, requested_at, sport)
    result = {
        "status": "OK",
        "plan": plan,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "quota_headers": quota_headers,
        "snapshot_timestamp": payload.get("timestamp"),
        "previous_timestamp": payload.get("previous_timestamp"),
        "next_timestamp": payload.get("next_timestamp"),
        "rows": rows,
        "promotion_eligible": False,
        "canonical_admission_required": True,
    }
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = requested_at.strftime("%Y%m%dT%H%M%SZ")
        raw_path = output_dir / f"{sport.lower()}_market_raw_{stamp}.json"
        rows_path = output_dir / f"{sport.lower()}_market_rows_{stamp}.jsonl"
        raw_path.write_bytes(_canonical({"request": plan, "response": payload, "quota_headers": quota_headers}))
        with rows_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        manifest = {
            "sport": sport,
            "snapshot_time_requested": requested_at.isoformat(),
            "snapshot_time_returned": payload.get("timestamp"),
            "source": "The Odds API historical odds",
            "raw_file": raw_path.name,
            "raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            "rows_file": rows_path.name,
            "rows_sha256": hashlib.sha256(rows_path.read_bytes()).hexdigest(),
            "rows": len(rows),
            "chronology_rule": "snapshot_time < event_time",
            "promotion_eligible": False,
            "canonical_admission_required": True,
            "quota_headers": quota_headers,
        }
        manifest_path = output_dir / f"{sport.lower()}_market_manifest_{stamp}.json"
        manifest_path.write_bytes(_canonical(manifest))
        result["artifacts"] = manifest
    return result


def fetch_event_snapshot(
    sport: str,
    provider_event_id: str,
    snapshot_time: str,
    *,
    regions: list[str],
    markets: list[str],
    execute: bool,
) -> dict[str, Any]:
    sport = sport.upper().strip()
    if sport not in SPORT_KEYS:
        raise ValueError("sport must be NFL, NBA, MLB or NHL")
    event_id = str(provider_event_id or "").strip()
    if not event_id or len(event_id) > 128:
        raise ValueError("provider event id is required")
    requested_at = _utc(snapshot_time)
    regions = [r.strip() for r in regions if r.strip()]
    markets = [m.strip() for m in markets if m.strip()]
    if not regions or not markets:
        raise ValueError("regions and markets are required")
    plan = {
        "sport": sport,
        "provider_event_id": event_id,
        "snapshot_time": requested_at.isoformat(),
        "regions": regions,
        "markets": markets,
        "estimated_max_credits": estimated_credits(markets, regions),
        "paid_historical_endpoint": True,
        "execution_requested": bool(execute),
        "execution_enabled": _enabled(),
    }
    if not execute:
        return {"status": "DRY_RUN", "plan": plan}
    if not _enabled():
        raise BackfillBlocked("set ODDS_HISTORICAL_BACKFILL_ENABLED=true to acknowledge paid historical usage")
    path = f"/v4/historical/sports/{SPORT_KEYS[sport]}/events/{event_id}/odds"
    payload, quota_headers = _get(
        path,
        {
            "regions": ",".join(regions),
            "markets": ",".join(markets),
            "date": requested_at.isoformat().replace("+00:00", "Z"),
            "dateFormat": "iso",
            "oddsFormat": "decimal",
        },
    )
    return {
        "status": "OK",
        "plan": plan,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "quota_headers": quota_headers,
        "snapshot_timestamp": payload.get("timestamp"),
        "payload": payload,
        "promotion_eligible": False,
        "canonical_admission_required": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Cost-gated The Odds API historical market capture")
    parser.add_argument("--sport", required=True, choices=sorted(SPORT_KEYS))
    parser.add_argument("--snapshot-time", required=True, help="ISO-8601 historical timestamp")
    parser.add_argument("--regions", default="us")
    parser.add_argument("--markets", default="h2h,spreads,totals")
    parser.add_argument("--event-id")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--execute", action="store_true", help="Actually consume paid API credits")
    args = parser.parse_args()
    regions = [x for x in args.regions.split(",") if x]
    markets = [x for x in args.markets.split(",") if x]
    if args.event_id:
        result = fetch_event_snapshot(
            args.sport, args.event_id, args.snapshot_time,
            regions=regions, markets=markets, execute=args.execute,
        )
    else:
        result = fetch_featured_snapshot(
            args.sport, args.snapshot_time,
            regions=regions, markets=markets, execute=args.execute,
            output_dir=args.output_dir,
        )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
