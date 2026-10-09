from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "backend" / "free_odds_gateway.py"
SNAPSHOT = ROOT / "backend" / "evidence" / "market_snapshot_store.py"
APP = ROOT / "backend" / "app.py"
LEDGER = ROOT / "backend" / "training" / "prediction_ledger.py"
GUARD = ROOT / "backend" / "ops" / "production_guard.py"
TESTS = ROOT / "backend" / "tests" / "test_free_odds_gateway.py"
LEGACY_APPLY = ROOT / "scripts" / "apply_free_odds_gateway.py"
VALIDATION_WORKFLOW = ROOT / ".github" / "workflows" / "apply-free-odds-gateway.yml"
DOCS = ROOT / "docs" / "FREE_ODDS_GATEWAY.md"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"{label}: expected anchor not found in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_regex(path: Path, pattern: str, replacement: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, lambda _: replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match in {path}, got {count}")
    path.write_text(updated, encoding="utf-8")


def patch_gateway() -> None:
    replace_once(GATEWAY, "import os\n", "import os\nimport re\n", "regex import")

    replace_regex(
        GATEWAY,
        r"ODDS_IO_SPORTS = \{.*?\}\n\n_PROP_HINTS:",
        '''ODDS_IO_SPORTS = {
    "NFL": "nfl",
    "NBA": "nba",
    "MLB": "mlb",
    "NHL": "nhl",
}
ODDS_IO_BOOKS = ["DraftKings", "FanDuel", "BetMGM", "Caesars", "BetRivers", "Bovada"]

_PROP_HINTS:''',
        "odds-api.io sport mapping",
    )

    replace_regex(
        GATEWAY,
        r"_PROP_HINTS: dict\[str, list\[tuple\[str, str\]\]\] = \{.*?\n\}\n\n\ndef _norm",
        '''_PROP_HINTS: dict[str, list[tuple[str, str]]] = {
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


def _norm''',
        "expanded prop mapping",
    )

    replace_regex(
        GATEWAY,
        r"def _same_event\(.*?(?=\n\ndef _request_json)",
        '''def _same_event(a: dict[str, Any], b: dict[str, Any]) -> bool:
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
''',
        "strict event matching",
    )

    replace_regex(
        GATEWAY,
        r"def _items\(.*?(?=\n\ndef _align_bookmaker)",
        '''def _items(payload: Any) -> list[dict[str, Any]]:
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
''',
        "nested response extraction",
    )

    replace_regex(
        GATEWAY,
        r"def _odds_io_game_events\(.*?(?=\ndef _sx_secondary_signal)",
        '''def _decimal_to_american(value: Any) -> int | None:
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

''',
        "odds-api.io normalization and props",
    )

    replace_regex(
        GATEWAY,
        r"def _sx_secondary_signal\(.*?(?=\ndef game_events)",
        '''def _sx_market_time(market: dict[str, Any]) -> datetime | None:
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

''',
        "event-specific SX signal",
    )

    replace_regex(
        GATEWAY,
        r"def game_events\(.*?(?=\n\ndef _prop_key)",
        '''def game_events(sport: str, target_date: date_cls, espn_events: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    sport = sport.upper()
    primary = list(espn_events or [])
    verification = _oddswrap_game_events(sport, target_date)
    sources: list[tuple[str, list[dict[str, Any]]]] = [("ODDSWRAP", verification)]

    def missing_primary(candidates: list[dict[str, Any]]) -> bool:
        if not primary:
            return not candidates
        return any(not any(_same_event(base, candidate) for candidate in candidates) for base in primary)

    coverage = list(verification)
    if missing_primary(coverage):
        propline = _propline_game_events(sport, target_date)
        sources.append(("PROPLINE", propline))
        coverage.extend(propline)
    if missing_primary(coverage):
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
        event["snapshot_evidence"] = (
            {
                "status": "RECORDED",
                "record_sha256": snapshot["record_sha256"],
                "fetched_at_utc": snapshot["fetched_at_utc"],
                "event_time_utc": snapshot["event_time_utc"],
                "chronology_valid": True,
                "sport": snapshot["sport"],
            }
            if snapshot else
            {"status": "NOT_RECORDED", "chronology_valid": False, "sport": sport}
        )
    return merged
''',
        "coverage-aware gateway routing",
    )

    replace_regex(
        GATEWAY,
        r"def _prop_key\(.*?(?=\n\ndef _split_game)",
        '''def _prop_key(sport: str, text: str) -> str | None:
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
''',
        "prop label normalization",
    )

    replace_regex(
        GATEWAY,
        r"def prop_event\(.*?(?=\n\ndef status)",
        '''def prop_event(sport: str, game: dict[str, Any], requested_markets: list[str]) -> dict[str, Any] | None:
    event = _oddswrap_prop_event(sport, game, requested_markets)
    if event is not None:
        return event
    event = _propline_prop_event(sport, game, requested_markets)
    if event is not None:
        return event
    event = _odds_io_prop_event(sport, game, requested_markets)
    if event is not None:
        return event
    return None
''',
        "player prop fallback order",
    )

    replace_regex(
        GATEWAY,
        r"def status\(\) -> dict\[str, Any\]:.*\Z",
        '''def status() -> dict[str, Any]:
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
''',
        "gateway status",
    )


def patch_snapshot_store() -> None:
    replace_once(
        SNAPSHOT,
        '''    record: dict[str, Any] = {
        "schema_version": "1",
        "sport": str(event.get("sport") or "").upper(),''',
        '''    sport = str(event.get("sport") or "").upper().strip()
    if not sport:
        return None

    record: dict[str, Any] = {
        "schema_version": "1",
        "sport": sport,''',
        "snapshot sport gate",
    )


def patch_app() -> None:
    replace_once(APP, 'APP_VERSION = "1.6.9"', 'APP_VERSION = "1.6.10"', "backend version")
    replace_once(
        APP,
        '''                    "market": market,
                    "projected_score": score,''',
        '''                    "market": market,
                    "market_source": oe.get("market_source") if oe else None,
                    "market_gateway": oe.get("gateway") if oe else {},
                    "market_snapshot_evidence": oe.get("snapshot_evidence") if oe else {},
                    "market_secondary_signals": oe.get("secondary_signals") if oe else {},
                    "projected_score": score,''',
        "search market evidence propagation",
    )


def patch_ledger() -> None:
    replace_once(
        LEDGER,
        '''                "market": market,
                "market_last_update": market.get("last_update"),''',
        '''                "market": market,
                "market_source": game.get("market_source"),
                "market_gateway": game.get("market_gateway") or {},
                "market_snapshot_evidence": game.get("market_snapshot_evidence") or {},
                "market_secondary_signals": game.get("market_secondary_signals") or {},
                "market_last_update": market.get("last_update"),''',
        "ledger gateway evidence",
    )
    replace_once(
        LEDGER,
        '''    missing_model_identity = []
    for row in rows:''',
        '''    missing_model_identity = []
    gateway_snapshot_failures = []
    for row in rows:''',
        "ledger snapshot failure accumulator",
    )
    replace_once(
        LEDGER,
        '''        if not row.get("model_id") or not row.get("model_artifact_sha256"):
            missing_model_identity.append(row.get("record_sha256"))

    settlement_path''',
        '''        if not row.get("model_id") or not row.get("model_artifact_sha256"):
            missing_model_identity.append(row.get("record_sha256"))
        if row.get("market_source") == "PHILTHY_FREE_ODDS_GATEWAY":
            snapshot = row.get("market_snapshot_evidence") or {}
            digest = str(snapshot.get("record_sha256") or "").lower()
            valid_digest = len(digest) == 64 and all(ch in "0123456789abcdef" for ch in digest)
            if snapshot.get("status") != "RECORDED" or snapshot.get("chronology_valid") is not True or not valid_digest:
                gateway_snapshot_failures.append(row.get("record_sha256"))

    settlement_path''',
        "ledger snapshot verification",
    )
    replace_once(
        LEDGER,
        '''        "passed": not chronology_failures and not hash_failures and not orphaned and not missing_model_identity,''',
        '''        "passed": (
            not chronology_failures
            and not hash_failures
            and not orphaned
            and not missing_model_identity
            and not gateway_snapshot_failures
        ),''',
        "ledger pass gate",
    )
    replace_once(
        LEDGER,
        '''        "missing_model_identity": missing_model_identity,
        "sports": by_sport,''',
        '''        "missing_model_identity": missing_model_identity,
        "gateway_snapshot_failures": gateway_snapshot_failures,
        "sports": by_sport,''',
        "ledger verification report",
    )


def patch_guard() -> None:
    replace_once(
        GUARD,
        '''        props = get_json(base + "/v1/system/props")
        evidence = get_json(base + "/v1/evidence/signals?limit=1")''',
        '''        props = get_json(base + "/v1/system/props")
        providers = get_json(base + "/v1/data/external-providers")
        evidence = get_json(base + "/v1/evidence/signals?limit=1")''',
        "production guard provider fetch",
    )
    replace_once(
        GUARD,
        '''        checks = {
            "health_ok": health.get("status") == "ok",''',
        '''        gateway = providers.get("free_odds_gateway") or {}
        checks = {
            "health_ok": health.get("status") == "ok",''',
        "production guard gateway state",
    )
    replace_once(
        GUARD,
        '''            "keyless_props_fallback": props.get("keyless_fallback_configured") is True,
            "manual_review_only": status.get("execution_mode") == "MANUAL_REVIEW_ONLY",''',
        '''            "keyless_props_fallback": props.get("keyless_fallback_configured") is True,
            "free_odds_gateway_identity": gateway.get("name") == "PhilthySports FreeOddsGateway",
            "free_odds_gateway_oddswrap": (gateway.get("oddswrap") or {}).get("available") is True,
            "free_odds_gateway_snapshot_gate": gateway.get("snapshot_gate") == "fetched_at < event_time",
            "free_odds_gateway_props_chain": gateway.get("player_props_order") == ["ODDSWRAP", "PROPLINE", "ODDS_API_IO"],
            "manual_review_only": status.get("execution_mode") == "MANUAL_REVIEW_ONLY",''',
        "production guard gateway checks",
    )
    replace_once(
        GUARD,
        '''            props_status=props.get("status"),
            evidence_storage={''',
        '''            props_status=props.get("status"),
            free_odds_gateway=gateway,
            evidence_storage={''',
        "production guard report",
    )


def patch_tests() -> None:
    text = TESTS.read_text(encoding="utf-8")
    marker = "def test_odds_api_io_v3_game_schema_is_normalized()"
    if marker in text:
        return
    text += '''


def test_same_event_rejects_distant_same_team_game():
    base = datetime.now(timezone.utc) + timedelta(hours=6)
    first = _event("A", "a", base)
    second = _event("B", "b", base + timedelta(minutes=31))
    assert gateway._same_event(first, second) is False


def test_odds_api_io_v3_game_schema_is_normalized():
    observed = datetime.now(timezone.utc).isoformat()
    event = {
        "id": 7,
        "home": "Seattle Seahawks",
        "away": "San Francisco 49ers",
        "date": (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat(),
    }
    payload = {
        **event,
        "bookmakers": {
            "DraftKings": [
                {"name": "ML", "updatedAt": observed, "odds": [{"home": "1.80", "away": "2.05"}]},
                {"name": "Spread", "updatedAt": observed, "odds": [{"hdp": -2.5, "home": "1.91", "away": "1.91"}]},
                {"name": "Totals", "updatedAt": observed, "odds": [{"hdp": 44.5, "over": "1.91", "under": "1.91"}]},
            ]
        },
    }
    row = gateway._normalize_odds_io_game(event, payload, observed)
    assert row is not None
    keys = [market["key"] for market in row["bookmakers"][0]["markets"]]
    assert keys == ["h2h", "spreads", "totals"]
    spread = row["bookmakers"][0]["markets"][1]
    assert spread["outcomes"][0]["point"] == -2.5
    assert spread["outcomes"][1]["point"] == 2.5


def test_odds_api_io_player_props_are_normalized():
    observed = datetime.now(timezone.utc).isoformat()
    game = {
        "event_id": "88",
        "home": "Seattle Seahawks",
        "away": "San Francisco 49ers",
        "event_time": (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat(),
    }
    event = {"id": 7, "home": game["home"], "away": game["away"], "date": game["event_time"]}
    payload = {
        "bookmakers": {
            "DraftKings": [{
                "name": "Player Props",
                "updatedAt": observed,
                "odds": [
                    {"label": "Player One (Receiving Yards)", "hdp": 64.5, "over": "1.91", "under": "1.91"},
                    {"label": "Player Two (Passing Yards)", "hdp": 249.5, "over": "1.85", "under": "1.95"},
                ],
            }]
        }
    }
    row = gateway._normalize_odds_io_props(
        "NFL", game, event, payload,
        ["player_reception_yds", "player_pass_yds"], observed,
    )
    assert row is not None
    keys = {market["key"] for market in row["bookmakers"][0]["markets"]}
    assert keys == {"player_reception_yds", "player_pass_yds"}


def test_gateway_sets_sport_before_snapshot(monkeypatch):
    when = datetime.now(timezone.utc) + timedelta(hours=12)
    espn = _event("ESPN_SCOREBOARD_ODDS", "espn", when)
    espn.pop("sport", None)
    monkeypatch.setattr(gateway, "_oddswrap_game_events", lambda sport, day: [])
    monkeypatch.setattr(gateway, "_propline_game_events", lambda sport, day: [])
    monkeypatch.setattr(gateway, "_odds_io_game_events", lambda sport, day: [])
    monkeypatch.setattr(gateway, "_sx_market_snapshot", lambda sport: {"available": False, "reason": "test", "markets": []})
    seen = {}

    def capture(event, fetched_at=None):
        seen["sport"] = event.get("sport")
        return {
            "record_sha256": "b" * 64,
            "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
            "event_time_utc": when.isoformat(),
            "sport": event.get("sport"),
        }

    monkeypatch.setattr(gateway, "record_market_snapshot", capture)
    rows = gateway.game_events("NFL", when.astimezone(gateway.PACIFIC).date(), [espn])
    assert rows[0]["sport"] == "NFL"
    assert seen["sport"] == "NFL"
    assert rows[0]["snapshot_evidence"]["sport"] == "NFL"
'''
    TESTS.write_text(text, encoding="utf-8")


def patch_legacy_apply() -> None:
    replace_once(
        LEGACY_APPLY,
        '''def main() -> None:
    patch_app()''',
        '''def main() -> None:
    current = APP.read_text(encoding="utf-8")
    if 'APP_VERSION = "1.6.10"' in current and 'market_snapshot_evidence' in current:
        print("FreeOddsGateway 1.6.10 is already integrated; legacy mutating patch skipped")
        return
    patch_app()''',
        "legacy apply safety guard",
    )


def patch_validation_workflow() -> None:
    VALIDATION_WORKFLOW.write_text('''name: Validate PhilthySports FreeOddsGateway

on:
  push:
    branches: [main]
    paths:
      - 'backend/app.py'
      - 'backend/free_odds_gateway.py'
      - 'backend/evidence/market_snapshot_store.py'
      - 'backend/outcome_validation.py'
      - 'backend/training/free_odds_evidence.py'
      - 'backend/training/prediction_ledger.py'
      - 'backend/ops/production_guard.py'
      - 'backend/tests/test_free_odds_gateway.py'
      - 'scripts/apply_free_odds_gateway.py'
      - '.github/workflows/apply-free-odds-gateway.yml'
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: validate-philthysports-free-odds-gateway
  cancel-in-progress: true

jobs:
  validate:
    runs-on: ubuntu-latest
    timeout-minutes: 25
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Validate syntax
        run: |
          python -m py_compile \\
            backend/app.py \\
            backend/free_odds_gateway.py \\
            backend/outcome_validation.py \\
            backend/evidence/market_snapshot_store.py \\
            backend/training/free_odds_evidence.py \\
            backend/training/prediction_ledger.py \\
            backend/ops/production_guard.py \\
            scripts/apply_free_odds_gateway.py

      - name: Install validation dependencies
        run: python -m pip install -q -r backend/requirements.txt -r backend/requirements-validation.txt

      - name: Run gateway regression suite
        env:
          PYTHONPATH: backend
        run: |
          pytest -q \\
            backend/tests/test_free_odds_gateway.py \\
            backend/tests/test_validation.py \\
            backend/tests/test_app.py
''', encoding="utf-8")


def patch_docs() -> None:
    text = DOCS.read_text(encoding="utf-8")
    marker = "## Hardening completion — 1.6.10"
    if marker in text:
        return
    text += '''

## Hardening completion — 1.6.10

The gateway now normalizes the current odds-api.io v3 bookmaker-map schema for ML, spread, total, and Player Props markets; uses odds-api.io only after ESPN/oddswrap/PropLine coverage remains incomplete; and fails closed on same-team events whose start times differ by more than 30 minutes.

ESPN-primary events are stamped with their sport before immutable hashing. The resulting snapshot hash, gateway provenance, and SX Bet event-scoped secondary signal are propagated into `/v1/search` and the immutable prediction ledger. The prediction-ledger verifier requires a valid chronology-marked snapshot hash for new FreeOddsGateway rows.

SX Bet remains read-only secondary evidence. The gateway matches SX markets to a specific event by teams and start time and never enables order placement.

The old self-mutating GitHub Action has been converted to validation-only. `scripts/apply_free_odds_gateway.py` now refuses to overwrite an already hardened 1.6.10 integration.
'''
    DOCS.write_text(text, encoding="utf-8")


def main() -> None:
    patch_gateway()
    patch_snapshot_store()
    patch_app()
    patch_ledger()
    patch_guard()
    patch_tests()
    patch_legacy_apply()
    patch_validation_workflow()
    patch_docs()
    print("FreeOddsGateway hardening patch applied")


if __name__ == "__main__":
    main()
