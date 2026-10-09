from __future__ import annotations

import os
from datetime import date as date_cls, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests

from evidence.market_snapshot_store import record_market_snapshot

PACIFIC = ZoneInfo("America/Los_Angeles")
ODDSWRAP_BOOKS = ["draftkings", "fanduel", "betmgm", "caesars", "betrivers", "bovada"]
ODDSWRAP_PROP_BOOKS = ["draftkings", "fanduel", "betrivers", "bovada"]
PROPLINE_BASE = os.getenv("PROPLINE_BASE_URL", "https://api.prop-line.com/v1").rstrip("/")
ODDS_IO_BASE = os.getenv("ODDS_API_IO_BASE_URL", "https://api.odds-api.io/v3").rstrip("/")
SX_BASE = os.getenv("SXBET_BASE_URL", "https://api.sx.bet").rstrip("/")

PROPLINE_SPORT_KEYS = {
    "NFL": ("football_nfl",),
    "NBA": ("basketball_nba",),
    "MLB": ("baseball_mlb",),
    "NHL": ("hockey_nhl", "icehockey_nhl"),
}
ODDS_IO_SPORTS = {
    "NFL": ("american-football", "usa-nfl"),
    "NBA": ("basketball", "usa-nba"),
    "MLB": ("baseball", None),
    "NHL": ("ice-hockey", None),
}

_PROP_HINTS: dict[str, list[tuple[str, str]]] = {
    "NFL": [
        ("passingyards", "player_pass_yds"), ("rushingyards", "player_rush_yds"),
        ("receivingyards", "player_reception_yds"), ("receptions", "player_receptions"),
        ("passingtouchdowns", "player_pass_tds"), ("passingcompletions", "player_pass_completions"),
        ("passingattempts", "player_pass_attempts"), ("passinginterceptions", "player_pass_interceptions"),
        ("rushingattempts", "player_rush_attempts"),
    ],
    "NBA": [
        ("pointsreboundsassists", "player_points_rebounds_assists"),
        ("pointsrebounds", "player_points_rebounds"), ("pointsassists", "player_points_assists"),
        ("reboundsassists", "player_rebounds_assists"), ("threepointers", "player_threes"),
        ("points", "player_points"), ("rebounds", "player_rebounds"),
        ("assists", "player_assists"), ("blocks", "player_blocks"),
        ("steals", "player_steals"), ("turnovers", "player_turnovers"),
    ],
    "MLB": [
        ("pitcherstrikeouts", "pitcher_strikeouts"), ("pitcherouts", "pitcher_outs"),
        ("pitcherhitsallowed", "pitcher_hits_allowed"), ("pitcherwalks", "pitcher_walks"),
        ("pitcherearnedruns", "pitcher_earned_runs"), ("homeruns", "batter_home_runs"),
        ("totalbases", "batter_total_bases"), ("hitsrunsrbis", "batter_hits_runs_rbis"),
        ("rbis", "batter_rbis"), ("runsscored", "batter_runs_scored"),
        ("stolenbases", "batter_stolen_bases"), ("strikeouts", "batter_strikeouts"),
        ("walks", "batter_walks"), ("hits", "batter_hits"),
    ],
    "NHL": [
        ("shotson goal", "player_shots_on_goal"), ("shotsongoal", "player_shots_on_goal"),
        ("powerplaypoints", "player_power_play_points"), ("blockedshots", "player_blocked_shots"),
        ("goaliesaves", "player_total_saves"), ("saves", "player_total_saves"),
        ("points", "player_points"), ("assists", "player_assists"), ("goals", "player_goals"),
    ],
}


def _norm(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _utc(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _same_team(a: Any, b: Any) -> bool:
    x, y = _norm(a), _norm(b)
    return bool(x and y and (x == y or x in y or y in x))


def _same_event(a: dict[str, Any], b: dict[str, Any]) -> bool:
    at = _utc(a.get("commence_time") or a.get("event_time") or a.get("start_time"))
    bt = _utc(b.get("commence_time") or b.get("event_time") or b.get("start_time"))
    if at is None or bt is None or abs((at - bt).total_seconds()) > 3 * 60 * 60:
        return False
    return (
        _same_team(a.get("home_team") or a.get("home"), b.get("home_team") or b.get("home"))
        and _same_team(a.get("away_team") or a.get("away"), b.get("away_team") or b.get("away"))
    )


def _request_json(url: str, *, params: dict[str, Any] | None = None, timeout: float = 12.0) -> Any:
    response = requests.get(url, params=params, timeout=timeout, headers={"Accept": "application/json"})
    response.raise_for_status()
    return response.json()


def _items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "events", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        if isinstance(value, dict):
            for nested in ("markets", "events", "items"):
                rows = value.get(nested)
                if isinstance(rows, list):
                    return [row for row in rows if isinstance(row, dict)]
    return []


def _align_bookmaker(book: dict[str, Any], source: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    out = {**book, "markets": []}
    src_home = source.get("home_team") or source.get("home")
    src_away = source.get("away_team") or source.get("away")
    target_home = target.get("home_team") or target.get("home")
    target_away = target.get("away_team") or target.get("away")
    for market in book.get("markets") or []:
        if not isinstance(market, dict):
            continue
        copy = {**market, "outcomes": []}
        for outcome in market.get("outcomes") or []:
            if not isinstance(outcome, dict):
                continue
            row = dict(outcome)
            if _same_team(row.get("name"), src_home):
                row["name"] = target_home
            elif _same_team(row.get("name"), src_away):
                row["name"] = target_away
            copy["outcomes"].append(row)
        out["markets"].append(copy)
    return out


def _merge_sources(primary: list[dict[str, Any]], sources: list[tuple[str, list[dict[str, Any]]]]) -> list[dict[str, Any]]:
    merged = [{**row, "bookmakers": list(row.get("bookmakers") or [])} for row in primary]
    provenance: dict[int, set[str]] = {id(row): {str(row.get("market_source") or "ESPN_SCOREBOARD_ODDS")} for row in merged}

    for label, events in sources:
        for event in events:
            target = next((row for row in merged if _same_event(row, event)), None)
            if target is None:
                target = {**event, "bookmakers": list(event.get("bookmakers") or [])}
                merged.append(target)
                provenance[id(target)] = {label}
                continue
            provenance.setdefault(id(target), set()).add(label)
            existing_keys = {
                str(book.get("key") or book.get("title") or "").lower()
                for book in target.get("bookmakers") or []
                if isinstance(book, dict)
            }
            for book in event.get("bookmakers") or []:
                if not isinstance(book, dict):
                    continue
                aligned = _align_bookmaker(book, event, target)
                key = str(aligned.get("key") or aligned.get("title") or "").lower()
                if not key or key in existing_keys:
                    continue
                target.setdefault("bookmakers", []).append(aligned)
                existing_keys.add(key)

    for row in merged:
        seen = sorted(provenance.get(id(row), set()))
        row["sport"] = str(row.get("sport") or "").upper()
        row["market_source"] = "PHILTHY_FREE_ODDS_GATEWAY"
        row["data_quality"] = "PREGAME_MULTI_SOURCE"
        row["gateway"] = {
            "primary": "ESPN_SCOREBOARD_ODDS",
            "verification": "ODDSWRAP",
            "fallback_order": ["PROPLINE", "ODDS_API_IO"],
            "secondary_signal": "SX_BET",
            "sources_seen": seen,
            "book_count": len(row.get("bookmakers") or []),
        }
    return merged


def _oddswrap_game_events(sport: str, target_date: date_cls) -> list[dict[str, Any]]:
    try:
        from oddswrap import OddsClient
    except Exception:
        return []
    try:
        games = OddsClient(books=ODDSWRAP_BOOKS).get_all(sport.lower())
    except Exception:
        return []
    observed = datetime.now(timezone.utc).isoformat()
    out: list[dict[str, Any]] = []
    for game in games:
        start = _utc(getattr(game, "start_time", None))
        if start is None or start.astimezone(PACIFIC).date() != target_date or getattr(game, "live", False):
            continue
        books: dict[str, dict[str, Any]] = {}
        for line in getattr(game, "lines", []) or []:
            name = str(getattr(line, "book", "") or "").strip()
            if not name:
                continue
            book = books.setdefault(name, {
                "key": name.lower(), "title": name, "observed_at": observed, "markets": []
            })
            stamp = getattr(line, "fetched_at", None) or observed
            home_odds, away_odds = getattr(line, "home_odds", None), getattr(line, "away_odds", None)
            if home_odds is not None and away_odds is not None:
                book["markets"].append({
                    "key": "h2h", "observed_at": stamp,
                    "outcomes": [
                        {"name": game.home_team, "price": home_odds},
                        {"name": game.away_team, "price": away_odds},
                    ],
                })
            hs, aws = getattr(line, "home_spread", None), getattr(line, "away_spread", None)
            hsp, asp = getattr(line, "home_spread_odds", None), getattr(line, "away_spread_odds", None)
            if None not in (hs, aws, hsp, asp):
                book["markets"].append({
                    "key": "spreads", "observed_at": stamp,
                    "outcomes": [
                        {"name": game.home_team, "point": hs, "price": hsp},
                        {"name": game.away_team, "point": aws, "price": asp},
                    ],
                })
            total, over, under = getattr(line, "total", None), getattr(line, "over_odds", None), getattr(line, "under_odds", None)
            if None not in (total, over, under):
                book["markets"].append({
                    "key": "totals", "observed_at": stamp,
                    "outcomes": [
                        {"name": "Over", "point": total, "price": over},
                        {"name": "Under", "point": total, "price": under},
                    ],
                })
        books = {key: value for key, value in books.items() if value["markets"]}
        if books:
            out.append({
                "id": str(getattr(game, "game_id", "") or f"oddswrap:{_norm(game.away_team)}:{_norm(game.home_team)}:{start.isoformat()}"),
                "sport": sport.upper(),
                "home_team": game.home_team,
                "away_team": game.away_team,
                "commence_time": start.isoformat(),
                "bookmakers": list(books.values()),
                "market_source": "ODDSWRAP",
                "data_quality": "PREGAME_FETCH_OBSERVED",
            })
    return out


def _propline_game_events(sport: str, target_date: date_cls) -> list[dict[str, Any]]:
    key = os.getenv("PROPLINE_API_KEY", "").strip()
    if not key:
        return []
    for sport_key in PROPLINE_SPORT_KEYS[sport.upper()]:
        try:
            payload = _request_json(
                f"{PROPLINE_BASE}/sports/{sport_key}/odds",
                params={"apiKey": key, "markets": "h2h,spreads,totals"},
            )
        except Exception:
            continue
        rows = _items(payload)
        out = []
        for row in rows:
            start = _utc(row.get("commence_time"))
            if start is None or start.astimezone(PACIFIC).date() != target_date:
                continue
            row = dict(row)
            row["sport"] = sport.upper()
            row["market_source"] = "PROPLINE"
            row["data_quality"] = "PREGAME_CREDENTIALLED_FREE_TIER"
            out.append(row)
        if out:
            return out
    return []


def _odds_io_game_events(sport: str, target_date: date_cls) -> list[dict[str, Any]]:
    key = os.getenv("ODDS_API_IO_KEY", "").strip()
    if not key:
        return []
    sport_slug, league_slug = ODDS_IO_SPORTS[sport.upper()]
    params: dict[str, Any] = {"apiKey": key, "sport": sport_slug, "status": "pending", "limit": 100}
    if league_slug:
        params["league"] = league_slug
    try:
        events = _items(_request_json(f"{ODDS_IO_BASE}/events", params=params))
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    observed = datetime.now(timezone.utc).isoformat()
    for event in events:
        start = _utc(event.get("date") or event.get("commence_time"))
        if start is None or start.astimezone(PACIFIC).date() != target_date:
            continue
        event_id = event.get("id")
        if event_id is None:
            continue
        try:
            payload = _request_json(f"{ODDS_IO_BASE}/odds", params={"apiKey": key, "eventId": event_id})
        except Exception:
            continue
        normalized = _normalize_odds_io(event, payload, observed)
        if normalized:
            normalized["sport"] = sport.upper()
            out.append(normalized)
    return out


def _decimal_to_american(value: Any) -> int | None:
    try:
        decimal = float(value)
    except (TypeError, ValueError):
        return None
    if decimal <= 1:
        return None
    return round((decimal - 1) * 100) if decimal >= 2 else round(-100 / (decimal - 1))


def _normalize_odds_io(event: dict[str, Any], payload: Any, observed: str) -> dict[str, Any] | None:
    if isinstance(payload, dict) and isinstance(payload.get("bookmakers"), list):
        row = dict(payload)
        row.setdefault("id", str(event.get("id") or ""))
        row.setdefault("home_team", event.get("home"))
        row.setdefault("away_team", event.get("away"))
        row.setdefault("commence_time", event.get("date"))
        for book in row.get("bookmakers") or []:
            if isinstance(book, dict):
                book.setdefault("observed_at", observed)
        row["market_source"] = "ODDS_API_IO"
        row["data_quality"] = "PREGAME_CREDENTIALLED_FREE_TIER"
        return row
    if not isinstance(payload, dict):
        return None
    home, away = event.get("home"), event.get("away")
    books: list[dict[str, Any]] = []
    source = payload.get("odds") if isinstance(payload.get("odds"), dict) else payload
    for book_name, markets in source.items():
        if not isinstance(markets, dict):
            continue
        normalized: list[dict[str, Any]] = []
        ml = markets.get("ML") or markets.get("Moneyline") or markets.get("moneyline")
        if isinstance(ml, dict):
            hp = _decimal_to_american(ml.get("home") or ml.get(str(home)))
            ap = _decimal_to_american(ml.get("away") or ml.get(str(away)))
            if hp is not None and ap is not None:
                normalized.append({"key": "h2h", "observed_at": observed, "outcomes": [
                    {"name": home, "price": hp}, {"name": away, "price": ap}
                ]})
        if normalized:
            books.append({"key": _norm(book_name), "title": str(book_name), "observed_at": observed, "markets": normalized})
    if not books:
        return None
    return {
        "id": str(event.get("id") or ""), "home_team": home, "away_team": away,
        "commence_time": event.get("date"), "bookmakers": books,
        "market_source": "ODDS_API_IO", "data_quality": "PREGAME_CREDENTIALLED_FREE_TIER",
    }


def _sx_secondary_signal(sport: str) -> dict[str, Any]:
    if os.getenv("PHILTHY_SXBET_ENABLED", "true").strip().lower() not in {"1", "true", "yes", "on"}:
        return {"available": False, "reason": "disabled"}
    try:
        sports = _items(_request_json(f"{SX_BASE}/sports", timeout=8))
        aliases = {
            "NFL": ("nfl", "football"), "NBA": ("nba", "basketball"),
            "MLB": ("mlb", "baseball"), "NHL": ("nhl", "hockey"),
        }[sport.upper()]
        match = next((row for row in sports if any(alias in _norm(row.get("name") or row.get("label")) for alias in aliases)), None)
        sport_id = (match or {}).get("id") or (match or {}).get("sportId")
        if sport_id is None:
            return {"available": False, "reason": "sport_not_found"}
        payload = _request_json(f"{SX_BASE}/markets/active", params={"sportIds": sport_id}, timeout=8)
        markets = _items(payload)
        return {
            "available": True,
            "source": "SX_BET",
            "sport_id": sport_id,
            "active_market_count": len(markets),
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "sample_market_hashes": [str(row.get("marketHash")) for row in markets[:5] if row.get("marketHash")],
            "role": "secondary_market_signal_only",
        }
    except Exception as exc:
        return {"available": False, "reason": type(exc).__name__, "source": "SX_BET"}


def game_events(sport: str, target_date: date_cls, espn_events: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    sport = sport.upper()
    primary = list(espn_events or [])
    verification = _oddswrap_game_events(sport, target_date)
    sources: list[tuple[str, list[dict[str, Any]]]] = [("ODDSWRAP", verification)]
    if not verification:
        propline = _propline_game_events(sport, target_date)
        sources.append(("PROPLINE", propline))
        if not propline:
            sources.append(("ODDS_API_IO", _odds_io_game_events(sport, target_date)))
    merged = _merge_sources(primary, sources)
    sx = _sx_secondary_signal(sport)
    now = datetime.now(timezone.utc)
    for event in merged:
        event.setdefault("secondary_signals", {})["sx_bet"] = sx
        snapshot = record_market_snapshot(event, fetched_at=now)
        event["snapshot_evidence"] = (
            {
                "status": "RECORDED",
                "record_sha256": snapshot["record_sha256"],
                "fetched_at_utc": snapshot["fetched_at_utc"],
                "event_time_utc": snapshot["event_time_utc"],
                "chronology_valid": True,
            }
            if snapshot else
            {"status": "NOT_RECORDED", "chronology_valid": False}
        )
    return merged


def _prop_key(sport: str, text: str) -> str | None:
    compact = _norm(text)
    for needle, key in _PROP_HINTS.get(sport.upper(), []):
        if _norm(needle) in compact:
            return key
    return None


def _split_game(value: str | None) -> tuple[str, str] | None:
    text = str(value or "")
    for sep in (" @ ", " vs ", " vs. "):
        if sep in text:
            away, home = text.split(sep, 1)
            if away.strip() and home.strip():
                return away.strip(), home.strip()
    return None


def _oddswrap_prop_event(sport: str, game: dict[str, Any], requested_markets: list[str]) -> dict[str, Any] | None:
    try:
        from oddswrap import OddsClient
    except Exception:
        return None
    observed = datetime.now(timezone.utc).isoformat()
    by_book: dict[str, dict[str, Any]] = {}
    for book in ODDSWRAP_PROP_BOOKS:
        client = OddsClient(books=[book])
        try:
            categories = client.get_prop_categories(sport.lower(), book=book)
        except Exception:
            continue
        for category in categories[:24]:
            market_key = _prop_key(
                sport,
                f"{getattr(category, 'category_name', '')} {getattr(category, 'subcategory_name', '')}",
            )
            if not market_key or market_key not in requested_markets:
                continue
            try:
                props = client.get_props(
                    sport.lower(),
                    str(category.category_id),
                    str(category.subcategory_id) if category.subcategory_id is not None else None,
                    book=book,
                )
            except Exception:
                continue
            for prop in props:
                teams = _split_game(getattr(prop, "game", None))
                if teams and not (
                    _same_team(teams[0], game.get("away")) and _same_team(teams[1], game.get("home"))
                ):
                    continue
                player = str(getattr(prop, "player", "") or "").strip()
                if not player:
                    continue
                outcomes = []
                line = getattr(prop, "line", None)
                over, under = getattr(prop, "over_odds", None), getattr(prop, "under_odds", None)
                if over is not None:
                    outcomes.append({"name": "Over", "description": player, "point": line, "price": over})
                if under is not None:
                    outcomes.append({"name": "Under", "description": player, "point": line, "price": under})
                if not outcomes:
                    continue
                stamp = getattr(prop, "fetched_at", None) or observed
                book_row = by_book.setdefault(book, {
                    "key": book, "title": book, "observed_at": observed, "markets": []
                })
                book_row["markets"].append({
                    "key": market_key,
                    "observed_at": stamp,
                    "outcomes": outcomes,
                })
    if not by_book:
        return None
    return {
        "id": str(game.get("event_id") or ""),
        "sport": sport.upper(),
        "home_team": game.get("home"),
        "away_team": game.get("away"),
        "commence_time": game.get("event_time"),
        "bookmakers": list(by_book.values()),
        "market_source": "ODDSWRAP_PROPS",
        "data_quality": "PREGAME_FETCH_OBSERVED",
    }


def _find_propline_event(sport: str, game: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    key = os.getenv("PROPLINE_API_KEY", "").strip()
    if not key:
        return None
    for sport_key in PROPLINE_SPORT_KEYS[sport.upper()]:
        try:
            events = _items(_request_json(f"{PROPLINE_BASE}/sports/{sport_key}/events", params={"apiKey": key}))
        except Exception:
            continue
        probe = {
            "home_team": game.get("home"), "away_team": game.get("away"),
            "commence_time": game.get("event_time"),
        }
        match = next((row for row in events if _same_event(probe, row)), None)
        if match is not None:
            return sport_key, match
    return None


def _propline_prop_event(sport: str, game: dict[str, Any], requested_markets: list[str]) -> dict[str, Any] | None:
    found = _find_propline_event(sport, game)
    if found is None:
        return None
    sport_key, event = found
    key = os.environ.get("PROPLINE_API_KEY", "").strip()
    try:
        payload = _request_json(
            f"{PROPLINE_BASE}/sports/{sport_key}/events/{event.get('id')}/odds",
            params={"apiKey": key, "markets": ",".join(requested_markets)},
        )
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    payload = dict(payload)
    payload.setdefault("id", str(event.get("id") or ""))
    payload.setdefault("home_team", event.get("home_team"))
    payload.setdefault("away_team", event.get("away_team"))
    payload.setdefault("commence_time", event.get("commence_time"))
    payload["market_source"] = "PROPLINE_PROPS"
    payload["data_quality"] = "PREGAME_CREDENTIALLED_FREE_TIER"
    observed = datetime.now(timezone.utc).isoformat()
    for book in payload.get("bookmakers") or []:
        if isinstance(book, dict):
            book.setdefault("observed_at", observed)
            for market in book.get("markets") or []:
                if isinstance(market, dict):
                    market.setdefault("observed_at", observed)
    return payload


def prop_event(sport: str, game: dict[str, Any], requested_markets: list[str]) -> dict[str, Any] | None:
    event = _oddswrap_prop_event(sport, game, requested_markets)
    if event is not None:
        return event
    event = _propline_prop_event(sport, game, requested_markets)
    if event is not None:
        return event
    return None


def status() -> dict[str, Any]:
    try:
        from oddswrap import OddsClient
        oddswrap_books = OddsClient(books=ODDSWRAP_BOOKS).available_books
        oddswrap_available = True
    except Exception:
        oddswrap_books = []
        oddswrap_available = False
    return {
        "name": "PhilthySports FreeOddsGateway",
        "game_odds_order": ["ESPN_KEYLESS", "ODDSWRAP", "PROPLINE", "ODDS_API_IO"],
        "player_props_order": ["ODDSWRAP", "PROPLINE", "ODDS_API_IO_SCHEMA_GUARDED"],
        "outcome_validation": ["ESPN", "MLB_STATSAPI", "NBA", "NHL_WEB_API"],
        "secondary_signal": "SX_BET",
        "snapshot_gate": "fetched_at < event_time",
        "oddswrap": {"available": oddswrap_available, "books": oddswrap_books},
        "propline": {"configured": bool(os.getenv("PROPLINE_API_KEY", "").strip())},
        "odds_api_io": {"configured": bool(os.getenv("ODDS_API_IO_KEY", "").strip())},
        "sx_bet": {"key_required_for_reads": False},
    }
