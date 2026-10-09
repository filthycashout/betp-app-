from __future__ import annotations

import os
import re
from datetime import date as date_cls, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests

from evidence.market_snapshot_store import record_market_snapshot, storage_status as market_snapshot_storage_status

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
    "NFL": "nfl",
    "NBA": "nba",
    "MLB": "mlb",
    "NHL": "nhl",
}
ODDS_IO_BOOKS = ["DraftKings", "FanDuel", "BetMGM", "Caesars", "BetRivers", "Bovada"]

_PROP_HINTS: dict[str, list[tuple[str, str]]] = {
    "NFL": [
        ("passrushreceptionyards", "player_pass_rush_reception_yds"),
        ("passingrushingreceivingyards", "player_pass_rush_reception_yds"),
        ("passingrushingyards", "player_pass_rush_yds"),
        ("rushreceivingyards", "player_rush_reception_yds"),
        ("rushingreceivingyards", "player_rush_reception_yds"),
        ("longestpassingcompletion", "player_pass_longest_completion"),
        ("longestreception", "player_reception_longest"),
        ("longestrush", "player_rush_longest"),
        ("passingyards", "player_pass_yds"),
        ("rushingyards", "player_rush_yds"),
        ("receivingyards", "player_reception_yds"),
        ("receptions", "player_receptions"),
        ("passingtouchdowns", "player_pass_tds"),
        ("rushingtouchdowns", "player_rush_tds"),
        ("receivingtouchdowns", "player_reception_tds"),
        ("passingcompletions", "player_pass_completions"),
        ("passingattempts", "player_pass_attempts"),
        ("passinginterceptions", "player_pass_interceptions"),
        ("rushingattempts", "player_rush_attempts"),
        ("anytimetouchdown", "player_anytime_td"),
        ("sacks", "player_sacks"),
        ("solotackles", "player_solo_tackles"),
        ("tacklesassists", "player_tackles_assists"),
    ],
    "NBA": [
        ("pointsreboundsassists", "player_points_rebounds_assists"),
        ("pointsrebounds", "player_points_rebounds"),
        ("pointsassists", "player_points_assists"),
        ("reboundsassists", "player_rebounds_assists"),
        ("blockssteals", "player_blocks_steals"),
        ("threepointers", "player_threes"),
        ("3pointers", "player_threes"),
        ("freethrowsattempted", "player_frees_attempts"),
        ("freethrowattempts", "player_frees_attempts"),
        ("freethrowsmade", "player_frees_made"),
        ("fieldgoalsmade", "player_field_goals"),
        ("points", "player_points"),
        ("rebounds", "player_rebounds"),
        ("assists", "player_assists"),
        ("blocks", "player_blocks"),
        ("steals", "player_steals"),
        ("turnovers", "player_turnovers"),
    ],
    "MLB": [
        ("pitcherstrikeouts", "pitcher_strikeouts"),
        ("pitcherouts", "pitcher_outs"),
        ("pitcherhitsallowed", "pitcher_hits_allowed"),
        ("pitcherwalks", "pitcher_walks"),
        ("pitcherearnedruns", "pitcher_earned_runs"),
        ("hitsrunsrbis", "batter_hits_runs_rbis"),
        ("homeruns", "batter_home_runs"),
        ("totalbases", "batter_total_bases"),
        ("runsbattedin", "batter_rbis"),
        ("rbis", "batter_rbis"),
        ("runsscored", "batter_runs_scored"),
        ("stolenbases", "batter_stolen_bases"),
        ("batterstrikeouts", "batter_strikeouts"),
        ("batterwalks", "batter_walks"),
        ("singles", "batter_singles"),
        ("doubles", "batter_doubles"),
        ("triples", "batter_triples"),
        ("hits", "batter_hits"),
    ],
    "NHL": [
        ("shotson goal", "player_shots_on_goal"),
        ("shotsongoal", "player_shots_on_goal"),
        ("powerplaypoints", "player_power_play_points"),
        ("blockedshots", "player_blocked_shots"),
        ("goaliesaves", "player_total_saves"),
        ("goalie saves", "player_total_saves"),
        ("saves", "player_total_saves"),
        ("points", "player_points"),
        ("assists", "player_assists"),
        ("goals", "player_goals"),
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
    at = _utc(a.get("commence_time") or a.get("event_time") or a.get("start_time") or a.get("date"))
    bt = _utc(b.get("commence_time") or b.get("event_time") or b.get("start_time") or b.get("date"))
    # Fail closed around doubleheaders and same-team rematches. Provider start
    # times can drift by a few minutes, but distinct events must never be merged.
    if at is None or bt is None or abs((at - bt).total_seconds()) > 30 * 60:
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
    for key in ("data", "events", "items", "sports", "leagues", "fixtures", "markets"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        if isinstance(value, dict):
            for nested in ("markets", "events", "items", "sports", "leagues", "fixtures"):
                rows = value.get(nested)
                if isinstance(rows, list):
                    return [row for row in rows if isinstance(row, dict)]
    return []


_REQUIRED_GAME_MARKETS = {"h2h", "spreads", "totals"}


def _market_fingerprint(market: dict[str, Any]) -> tuple[Any, ...]:
    outcomes = []
    for outcome in market.get("outcomes") or []:
        if not isinstance(outcome, dict):
            continue
        outcomes.append((
            _norm(outcome.get("name")),
            outcome.get("point"),
            outcome.get("description"),
        ))
    return (str(market.get("key") or "").lower(), tuple(outcomes))


def _event_market_keys(event: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for book in event.get("bookmakers") or []:
        if not isinstance(book, dict):
            continue
        for market in book.get("markets") or []:
            if isinstance(market, dict) and market.get("key"):
                keys.add(str(market["key"]).lower())
    return keys


def _primary_market_coverage_complete(
    primary: list[dict[str, Any]], candidates: list[dict[str, Any]]
) -> bool:
    if not primary:
        return bool(candidates)
    for base in primary:
        covered: set[str] = set()
        for candidate in candidates:
            if _same_event(base, candidate):
                covered.update(_event_market_keys(candidate))
        if not _REQUIRED_GAME_MARKETS.issubset(covered):
            return False
    return True


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
            book_index = {
                str(book.get("key") or book.get("title") or "").lower(): book
                for book in target.get("bookmakers") or []
                if isinstance(book, dict)
            }
            for book in event.get("bookmakers") or []:
                if not isinstance(book, dict):
                    continue
                aligned = _align_bookmaker(book, event, target)
                key = str(aligned.get("key") or aligned.get("title") or "").lower()
                if not key:
                    continue
                existing = book_index.get(key)
                if existing is None:
                    target.setdefault("bookmakers", []).append(aligned)
                    book_index[key] = aligned
                    continue
                fingerprints = {
                    _market_fingerprint(market)
                    for market in existing.get("markets") or []
                    if isinstance(market, dict)
                }
                for market in aligned.get("markets") or []:
                    if not isinstance(market, dict):
                        continue
                    fingerprint = _market_fingerprint(market)
                    if fingerprint not in fingerprints:
                        existing.setdefault("markets", []).append(market)
                        fingerprints.add(fingerprint)

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


def _decimal_to_american(value: Any) -> int | None:
    try:
        decimal = float(value)
    except (TypeError, ValueError):
        return None
    if decimal <= 1:
        return None
    return round((decimal - 1) * 100) if decimal >= 2 else round(-100 / (decimal - 1))


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _odds_io_events(sport: str) -> list[dict[str, Any]]:
    key = os.getenv("ODDS_API_IO_KEY", "").strip()
    if not key:
        return []
    params = {
        "apiKey": key,
        "sport": ODDS_IO_SPORTS[sport.upper()],
        "status": "pending",
        "limit": 100,
    }
    try:
        return _items(_request_json(f"{ODDS_IO_BASE}/events", params=params))
    except Exception:
        return []


def _normalize_odds_io_game(event: dict[str, Any], payload: Any, observed: str) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    home = payload.get("home") or event.get("home") or event.get("home_team")
    away = payload.get("away") or event.get("away") or event.get("away_team")
    start = payload.get("date") or event.get("date") or event.get("commence_time")
    books_raw = payload.get("bookmakers")

    # Some deployments expose The-Odds-API-compatible bookmaker arrays. Keep
    # accepting that shape, but stamp the observation time if the provider did not.
    if isinstance(books_raw, list):
        row = {
            **payload,
            "id": str(payload.get("id") or event.get("id") or ""),
            "home_team": payload.get("home_team") or home,
            "away_team": payload.get("away_team") or away,
            "commence_time": payload.get("commence_time") or start,
            "market_source": "ODDS_API_IO",
            "data_quality": "PREGAME_CREDENTIALLED_FREE_TIER",
        }
        for book in row.get("bookmakers") or []:
            if isinstance(book, dict):
                book.setdefault("observed_at", observed)
                for market in book.get("markets") or []:
                    if isinstance(market, dict):
                        market.setdefault("observed_at", book.get("observed_at") or observed)
        return row

    # Current odds-api.io v3 uses a bookmaker-name -> market-list mapping.
    if not isinstance(books_raw, dict):
        return None
    books: list[dict[str, Any]] = []
    for book_name, market_rows in books_raw.items():
        if not isinstance(market_rows, list):
            continue
        normalized_markets: list[dict[str, Any]] = []
        for market in market_rows:
            if not isinstance(market, dict):
                continue
            market_name = _norm(market.get("name"))
            updated = market.get("updatedAt") or market.get("updated_at") or observed
            quotes = market.get("odds") or []
            if not isinstance(quotes, list):
                continue
            for quote in quotes:
                if not isinstance(quote, dict):
                    continue
                if market_name in {"ml", "moneyline", "h2h"}:
                    hp = _decimal_to_american(quote.get("home"))
                    ap = _decimal_to_american(quote.get("away"))
                    if hp is not None and ap is not None:
                        normalized_markets.append({
                            "key": "h2h", "observed_at": updated,
                            "outcomes": [
                                {"name": home, "price": hp},
                                {"name": away, "price": ap},
                            ],
                        })
                elif market_name in {"spread", "spreads", "handicap"}:
                    point = _as_float(quote.get("hdp") if quote.get("hdp") is not None else quote.get("handicap"))
                    hp = _decimal_to_american(quote.get("home"))
                    ap = _decimal_to_american(quote.get("away"))
                    if point is not None and hp is not None and ap is not None:
                        normalized_markets.append({
                            "key": "spreads", "observed_at": updated,
                            "outcomes": [
                                {"name": home, "point": point, "price": hp},
                                {"name": away, "point": -point, "price": ap},
                            ],
                        })
                elif market_name in {"total", "totals", "overunder"}:
                    point = _as_float(quote.get("hdp") if quote.get("hdp") is not None else quote.get("total"))
                    over = _decimal_to_american(quote.get("over"))
                    under = _decimal_to_american(quote.get("under"))
                    if point is not None and over is not None and under is not None:
                        normalized_markets.append({
                            "key": "totals", "observed_at": updated,
                            "outcomes": [
                                {"name": "Over", "point": point, "price": over},
                                {"name": "Under", "point": point, "price": under},
                            ],
                        })
        if normalized_markets:
            books.append({
                "key": _norm(book_name),
                "title": str(book_name),
                "observed_at": observed,
                "markets": normalized_markets,
            })
    if not books:
        return None
    return {
        "id": str(payload.get("id") or event.get("id") or ""),
        "home_team": home,
        "away_team": away,
        "commence_time": start,
        "bookmakers": books,
        "market_source": "ODDS_API_IO",
        "data_quality": "PREGAME_CREDENTIALLED_FREE_TIER",
    }


def _odds_io_game_events(sport: str, target_date: date_cls) -> list[dict[str, Any]]:
    key = os.getenv("ODDS_API_IO_KEY", "").strip()
    if not key:
        return []
    observed = datetime.now(timezone.utc).isoformat()
    out: list[dict[str, Any]] = []
    for event in _odds_io_events(sport):
        start = _utc(event.get("date") or event.get("commence_time"))
        if start is None or start.astimezone(PACIFIC).date() != target_date:
            continue
        event_id = event.get("id")
        if event_id is None:
            continue
        try:
            payload = _request_json(
                f"{ODDS_IO_BASE}/odds",
                params={
                    "apiKey": key,
                    "eventId": event_id,
                    "bookmakers": ",".join(ODDS_IO_BOOKS),
                    "markets": "ML,Spread,Totals",
                },
            )
        except Exception:
            continue
        normalized = _normalize_odds_io_game(event, payload, observed)
        if normalized is not None:
            normalized["sport"] = sport.upper()
            out.append(normalized)
    return out


def _split_odds_io_prop_label(label: Any) -> tuple[str, str] | None:
    text = str(label or "").strip()
    if not text:
        return None
    match = re.match(r"^(.+?)\s*\(([^()]+)\)\s*$", text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    match = re.match(r"^(.+?)\s*[-–—]\s*(.+)$", text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return None


def _normalize_odds_io_props(
    sport: str,
    game: dict[str, Any],
    event: dict[str, Any],
    payload: Any,
    requested_markets: list[str],
    observed: str,
) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("bookmakers"), dict):
        return None
    by_book: list[dict[str, Any]] = []
    for book_name, market_rows in payload["bookmakers"].items():
        if not isinstance(market_rows, list):
            continue
        grouped: dict[str, dict[str, Any]] = {}
        for market in market_rows:
            if not isinstance(market, dict) or "playerprops" not in _norm(market.get("name")):
                continue
            updated = market.get("updatedAt") or market.get("updated_at") or observed
            for quote in market.get("odds") or []:
                if not isinstance(quote, dict):
                    continue
                parsed = _split_odds_io_prop_label(quote.get("label"))
                if parsed is None:
                    continue
                player, prop_label = parsed
                market_key = _prop_key(sport, prop_label)
                if market_key is None or market_key not in requested_markets:
                    continue
                over = _decimal_to_american(quote.get("over"))
                under = _decimal_to_american(quote.get("under"))
                if over is None and under is None:
                    continue
                line = _as_float(quote.get("hdp"))
                row = grouped.setdefault(market_key, {
                    "key": market_key,
                    "observed_at": updated,
                    "outcomes": [],
                })
                if over is not None:
                    row["outcomes"].append({
                        "name": "Over", "description": player, "point": line, "price": over,
                    })
                if under is not None:
                    row["outcomes"].append({
                        "name": "Under", "description": player, "point": line, "price": under,
                    })
        if grouped:
            by_book.append({
                "key": _norm(book_name),
                "title": str(book_name),
                "observed_at": observed,
                "markets": list(grouped.values()),
            })
    if not by_book:
        return None
    return {
        "id": str(game.get("event_id") or event.get("id") or ""),
        "sport": sport.upper(),
        "home_team": game.get("home"),
        "away_team": game.get("away"),
        "commence_time": game.get("event_time") or event.get("date"),
        "bookmakers": by_book,
        "market_source": "ODDS_API_IO_PROPS",
        "data_quality": "PREGAME_CREDENTIALLED_FREE_TIER",
    }


def _odds_io_prop_event(sport: str, game: dict[str, Any], requested_markets: list[str]) -> dict[str, Any] | None:
    key = os.getenv("ODDS_API_IO_KEY", "").strip()
    if not key:
        return None
    probe = {
        "home_team": game.get("home"),
        "away_team": game.get("away"),
        "commence_time": game.get("event_time"),
    }
    event = next((row for row in _odds_io_events(sport) if _same_event(probe, row)), None)
    if event is None:
        return None
    observed = datetime.now(timezone.utc).isoformat()
    try:
        payload = _request_json(
            f"{ODDS_IO_BASE}/odds",
            params={
                "apiKey": key,
                "eventId": event.get("id"),
                "bookmakers": ",".join(ODDS_IO_BOOKS),
                "markets": "Player Props",
            },
        )
    except Exception:
        return None
    return _normalize_odds_io_props(sport, game, event, payload, requested_markets, observed)


def _sx_market_time(market: dict[str, Any]) -> datetime | None:
    raw = market.get("gameTime") or market.get("game_time") or market.get("startTime")
    if isinstance(raw, (int, float)):
        value = float(raw)
        if value > 10_000_000_000:
            value /= 1000.0
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    return _utc(raw)


def _sx_market_snapshot(sport: str) -> dict[str, Any]:
    if os.getenv("PHILTHY_SXBET_ENABLED", "true").strip().lower() not in {"1", "true", "yes", "on"}:
        return {"available": False, "reason": "disabled", "markets": []}
    try:
        sports = _items(_request_json(f"{SX_BASE}/sports", timeout=8))
        aliases = {
            "NFL": ("nfl", "football"), "NBA": ("nba", "basketball"),
            "MLB": ("mlb", "baseball"), "NHL": ("nhl", "hockey"),
        }[sport.upper()]
        match = next(
            (
                row for row in sports
                if any(alias in _norm(row.get("name") or row.get("label") or row.get("slug")) for alias in aliases)
            ),
            None,
        )
        sport_id = (match or {}).get("id") or (match or {}).get("sportId")
        if sport_id is None:
            return {"available": False, "reason": "sport_not_found", "markets": []}
        payload = _request_json(
            f"{SX_BASE}/markets/active",
            params={"sportIds": sport_id, "onlyMainLine": "true"},
            timeout=8,
        )
        return {
            "available": True,
            "source": "SX_BET",
            "sport_id": sport_id,
            "markets": _items(payload),
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        return {"available": False, "reason": type(exc).__name__, "source": "SX_BET", "markets": []}


def _sx_secondary_signal(sport: str) -> dict[str, Any]:
    snapshot = _sx_market_snapshot(sport)
    return {key: value for key, value in snapshot.items() if key != "markets"}


def _sx_market_teams(market: dict[str, Any]) -> tuple[str, str] | None:
    first = market.get("teamOneName") or market.get("outcomeOneName")
    second = market.get("teamTwoName") or market.get("outcomeTwoName")
    if first and second:
        return str(first), str(second)
    label = str(market.get("gameLabel") or market.get("label") or "")
    for sep in (" @ ", " vs ", " vs. "):
        if sep in label:
            a, b = label.split(sep, 1)
            if a.strip() and b.strip():
                return a.strip(), b.strip()
    return None


def _sx_signal_for_event(snapshot: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    if snapshot.get("available") is not True:
        return {k: v for k, v in snapshot.items() if k != "markets"}
    target_time = _utc(event.get("commence_time") or event.get("event_time"))
    home = event.get("home_team") or event.get("home")
    away = event.get("away_team") or event.get("away")
    matches = []
    for market in snapshot.get("markets") or []:
        if not isinstance(market, dict):
            continue
        teams = _sx_market_teams(market)
        market_time = _sx_market_time(market)
        if teams is None or target_time is None or market_time is None:
            continue
        if abs((market_time - target_time).total_seconds()) > 30 * 60:
            continue
        direct = _same_team(teams[0], away) and _same_team(teams[1], home)
        swapped = _same_team(teams[1], away) and _same_team(teams[0], home)
        if direct or swapped:
            matches.append(market)
    return {
        "available": True,
        "matched": bool(matches),
        "source": "SX_BET",
        "sport_id": snapshot.get("sport_id"),
        "observed_at": snapshot.get("observed_at"),
        "active_market_count": len(matches),
        "market_hashes": [str(row.get("marketHash")) for row in matches[:20] if row.get("marketHash")],
        "role": "secondary_market_signal_only",
    }


def game_events(sport: str, target_date: date_cls, espn_events: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    sport = sport.upper()
    primary = list(espn_events or [])
    verification = _oddswrap_game_events(sport, target_date)
    sources: list[tuple[str, list[dict[str, Any]]]] = [("ODDSWRAP", verification)]

    coverage = list(verification)
    if not _primary_market_coverage_complete(primary, coverage):
        propline = _propline_game_events(sport, target_date)
        sources.append(("PROPLINE", propline))
        coverage.extend(propline)
    if not _primary_market_coverage_complete(primary, coverage):
        odds_io = _odds_io_game_events(sport, target_date)
        sources.append(("ODDS_API_IO", odds_io))
        coverage.extend(odds_io)

    merged = _merge_sources(primary, sources)
    sx_snapshot = _sx_market_snapshot(sport)
    now = datetime.now(timezone.utc)
    for event in merged:
        # The ESPN primary adapter does not attach sport itself. Set it before
        # hashing/persisting so the immutable row is queryable by league.
        event["sport"] = sport
        event.setdefault("secondary_signals", {})["sx_bet"] = _sx_signal_for_event(sx_snapshot, event)
        snapshot = record_market_snapshot(event, fetched_at=now)
        storage = market_snapshot_storage_status()
        event["snapshot_evidence"] = (
            {
                "status": "RECORDED" if storage.get("durable") is True else "RECORDED_NON_DURABLE",
                "record_sha256": snapshot["record_sha256"],
                "fetched_at_utc": snapshot["fetched_at_utc"],
                "event_time_utc": snapshot["event_time_utc"],
                "chronology_valid": True,
                "sport": snapshot.get("sport") or sport,
                "durable": storage.get("durable") is True,
                "storage_mode": storage.get("mode"),
            }
            if snapshot else
            {
                "status": "NOT_RECORDED",
                "chronology_valid": False,
                "sport": sport,
                "durable": False,
                "storage_mode": storage.get("mode"),
            }
        )
    return merged


def _prop_key(sport: str, text: str) -> str | None:
    compact = _norm(text)
    for structural in ("props", "overunder", "ou"):
        compact = compact.replace(structural, "")
    for needle, key in _PROP_HINTS.get(sport.upper(), []):
        candidate = _norm(needle)
        for structural in ("props", "overunder", "ou"):
            candidate = candidate.replace(structural, "")
        if candidate and candidate in compact:
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


def _clone_prop_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        **event,
        "bookmakers": [
            {
                **book,
                "markets": [dict(market) for market in book.get("markets") or [] if isinstance(market, dict)],
            }
            for book in event.get("bookmakers") or []
            if isinstance(book, dict)
        ],
    }


def _merge_prop_event(base: dict[str, Any] | None, addition: dict[str, Any]) -> dict[str, Any]:
    if base is None:
        return _clone_prop_event(addition)
    book_index = {
        str(book.get("key") or book.get("title") or "").lower(): book
        for book in base.get("bookmakers") or []
        if isinstance(book, dict)
    }
    for book in addition.get("bookmakers") or []:
        if not isinstance(book, dict):
            continue
        key = str(book.get("key") or book.get("title") or "").lower()
        if not key:
            continue
        existing = book_index.get(key)
        if existing is None:
            cloned = {**book, "markets": [dict(m) for m in book.get("markets") or [] if isinstance(m, dict)]}
            base.setdefault("bookmakers", []).append(cloned)
            book_index[key] = cloned
            continue
        fingerprints = {
            _market_fingerprint(market)
            for market in existing.get("markets") or []
            if isinstance(market, dict)
        }
        for market in book.get("markets") or []:
            if not isinstance(market, dict):
                continue
            fingerprint = _market_fingerprint(market)
            if fingerprint not in fingerprints:
                existing.setdefault("markets", []).append(dict(market))
                fingerprints.add(fingerprint)
    return base


def prop_event(sport: str, game: dict[str, Any], requested_markets: list[str]) -> dict[str, Any] | None:
    requested = list(dict.fromkeys(requested_markets))
    composite: dict[str, Any] | None = None
    sources_seen: list[str] = []

    oddswrap = _oddswrap_prop_event(sport, game, requested)
    if oddswrap is not None:
        composite = _merge_prop_event(composite, oddswrap)
        sources_seen.append("ODDSWRAP")

    covered = _event_market_keys(composite or {})
    missing = [market for market in requested if market not in covered]
    if missing:
        propline = _propline_prop_event(sport, game, missing)
        if propline is not None:
            composite = _merge_prop_event(composite, propline)
            sources_seen.append("PROPLINE")

    covered = _event_market_keys(composite or {})
    missing = [market for market in requested if market not in covered]
    if missing:
        odds_io = _odds_io_prop_event(sport, game, missing)
        if odds_io is not None:
            composite = _merge_prop_event(composite, odds_io)
            sources_seen.append("ODDS_API_IO")

    if composite is None:
        return None
    covered = _event_market_keys(composite)
    composite["market_source"] = "PHILTHY_FREE_ODDS_GATEWAY_PROPS"
    composite["gateway"] = {
        "sources_seen": sources_seen,
        "requested_markets": requested,
        "covered_markets": sorted(covered.intersection(requested)),
        "complete": all(market in covered for market in requested),
    }
    return composite


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
        "player_props_order": ["ODDSWRAP", "PROPLINE", "ODDS_API_IO"],
        "outcome_validation": ["ESPN", "MLB_STATSAPI", "NBA", "NHL_WEB_API"],
        "secondary_signal": "SX_BET_EVENT_MATCHED",
        "snapshot_gate": "fetched_at < event_time",
        "snapshot_storage": market_snapshot_storage_status(),
        "event_match_tolerance_seconds": 1800,
        "oddswrap": {"available": oddswrap_available, "books": oddswrap_books},
        "propline": {
            "configured": bool(os.getenv("PROPLINE_API_KEY", "").strip()),
            "tier": "credentialled_free_fallback",
        },
        "odds_api_io": {
            "configured": bool(os.getenv("ODDS_API_IO_KEY", "").strip()),
            "game_markets": ["ML", "Spread", "Totals"],
            "player_props": True,
        },
        "sx_bet": {"key_required_for_reads": False, "event_scoped": True},
    }
