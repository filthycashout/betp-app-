from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "backend" / "free_odds_gateway.py"
APP = ROOT / "backend" / "app.py"
TESTS = ROOT / "backend" / "tests" / "test_free_odds_gateway.py"
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
    replace_once(
        GATEWAY,
        "import os\nimport re\nfrom datetime",
        "import os\nimport re\nimport threading\nimport time\nfrom concurrent.futures import ThreadPoolExecutor, as_completed\nfrom datetime",
        "concurrency imports",
    )
    replace_once(
        GATEWAY,
        '''SX_BASE = os.getenv("SXBET_BASE_URL", "https://api.sx.bet").rstrip("/")
''',
        '''SX_BASE = os.getenv("SXBET_BASE_URL", "https://api.sx.bet").rstrip("/")
_GATEWAY_CACHE_TTL_SECONDS = max(10, int(os.getenv("PHILTHY_FREE_ODDS_CACHE_TTL_SECONDS", "45")))
_SX_TIMEOUT_SECONDS = max(1.0, float(os.getenv("PHILTHY_SXBET_TIMEOUT_SECONDS", "3")))
_GATEWAY_CACHE: dict[tuple[Any, ...], tuple[float, Any]] = {}
_GATEWAY_CACHE_LOCK = threading.RLock()


def _cached_value(key: tuple[Any, ...], ttl: float, factory):
    now = time.monotonic()
    with _GATEWAY_CACHE_LOCK:
        hit = _GATEWAY_CACHE.get(key)
        if hit is not None and now - hit[0] <= ttl:
            return hit[1]
    value = factory()
    with _GATEWAY_CACHE_LOCK:
        _GATEWAY_CACHE[key] = (time.monotonic(), value)
    return value
''',
        "gateway cache",
    )

    replace_regex(
        GATEWAY,
        r"def _oddswrap_game_events\(sport: str, target_date: date_cls\) -> list\[dict\[str, Any\]\]:.*?(?=\n\ndef _propline_game_events)",
        '''def _oddswrap_game_events(sport: str, target_date: date_cls) -> list[dict[str, Any]]:
    cache_key = ("oddswrap-games", sport.upper(), target_date.isoformat())

    def build() -> list[dict[str, Any]]:
        try:
            from oddswrap import OddsClient
        except Exception:
            return []
        client = OddsClient(books=ODDSWRAP_BOOKS)
        method_names = ("get_moneylines", "get_spreads", "get_totals")
        raw_games = []
        # oddswrap.get_all() intentionally fetches the three market families
        # sequentially. The Philthy gateway runs those independent reads in
        # parallel so one slow sportsbook family cannot triple board latency.
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="philthy-oddswrap-games") as pool:
            futures = [pool.submit(getattr(client, method), sport.lower()) for method in method_names]
            for future in as_completed(futures):
                try:
                    raw_games.extend(future.result())
                except Exception:
                    continue
        try:
            games = client._merge(raw_games)  # pinned oddswrap v1.3.0 merge contract
        except Exception:
            games = raw_games

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

    return _cached_value(cache_key, _GATEWAY_CACHE_TTL_SECONDS, build)
''',
        "parallel cached oddswrap games",
    )

    replace_regex(
        GATEWAY,
        r"def _sx_market_snapshot\(sport: str\) -> dict\[str, Any\]:.*?(?=\n\ndef _sx_secondary_signal)",
        '''def _sx_market_snapshot(sport: str) -> dict[str, Any]:
    cache_key = ("sx-market-snapshot", sport.upper())

    def build() -> dict[str, Any]:
        if os.getenv("PHILTHY_SXBET_ENABLED", "true").strip().lower() not in {"1", "true", "yes", "on"}:
            return {"available": False, "reason": "disabled", "markets": []}
        try:
            sports = _items(_request_json(f"{SX_BASE}/sports", timeout=_SX_TIMEOUT_SECONDS))
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
                timeout=_SX_TIMEOUT_SECONDS,
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

    return _cached_value(cache_key, _GATEWAY_CACHE_TTL_SECONDS, build)
''',
        "cached fail-fast SX",
    )

    replace_once(
        GATEWAY,
        '''    primary = list(espn_events or [])
    verification = _oddswrap_game_events(sport, target_date)
    sources: list[tuple[str, list[dict[str, Any]]]] = [("ODDSWRAP", verification)]
''',
        '''    primary = list(espn_events or [])
    # Verification and the secondary SX signal are independent reads. Do not
    # serialize them on latency-sensitive board/search requests.
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="philthy-game-sources") as pool:
        verification_future = pool.submit(_oddswrap_game_events, sport, target_date)
        sx_future = pool.submit(_sx_market_snapshot, sport)
        try:
            verification = verification_future.result()
        except Exception:
            verification = []
        try:
            sx_snapshot = sx_future.result()
        except Exception as exc:
            sx_snapshot = {"available": False, "reason": type(exc).__name__, "markets": []}
    sources: list[tuple[str, list[dict[str, Any]]]] = [("ODDSWRAP", verification)]
''',
        "parallel SX and verification",
    )
    replace_once(
        GATEWAY,
        '''    merged = _merge_sources(primary, sources)
    sx_snapshot = _sx_market_snapshot(sport)
    now = datetime.now(timezone.utc)''',
        '''    merged = _merge_sources(primary, sources)
    now = datetime.now(timezone.utc)''',
        "reuse SX snapshot",
    )

    replace_regex(
        GATEWAY,
        r"def _oddswrap_prop_event\(sport: str, game: dict\[str, Any\], requested_markets: list\[str\]\) -> dict\[str, Any\] \| None:.*?(?=\n\ndef _find_propline_event)",
        '''def _oddswrap_prop_catalog(sport: str, requested_markets: list[str]) -> list[dict[str, Any]]:
    requested = tuple(sorted(set(requested_markets)))
    cache_key = ("oddswrap-prop-catalog", sport.upper(), *requested)

    def build() -> list[dict[str, Any]]:
        try:
            from oddswrap import OddsClient
        except Exception:
            return []

        selected: list[tuple[str, Any, str]] = []

        def discover(book: str) -> list[tuple[str, Any, str]]:
            client = OddsClient(books=[book])
            try:
                categories = client.get_prop_categories(sport.lower(), book=book)
            except Exception:
                return []
            rows: list[tuple[str, Any, str]] = []
            per_market: dict[str, int] = {}
            # Two provider categories per requested normalized market is enough to
            # preserve alternate-category coverage without an unbounded fan-out.
            for category in categories[:48]:
                market_key = _prop_key(
                    sport,
                    f"{getattr(category, 'category_name', '')} {getattr(category, 'subcategory_name', '')}",
                )
                if not market_key or market_key not in requested:
                    continue
                if per_market.get(market_key, 0) >= 2:
                    continue
                per_market[market_key] = per_market.get(market_key, 0) + 1
                rows.append((book, category, market_key))
            return rows

        with ThreadPoolExecutor(max_workers=len(ODDSWRAP_PROP_BOOKS), thread_name_prefix="philthy-prop-discovery") as pool:
            futures = [pool.submit(discover, book) for book in ODDSWRAP_PROP_BOOKS]
            for future in as_completed(futures):
                try:
                    selected.extend(future.result())
                except Exception:
                    continue

        def fetch_one(task: tuple[str, Any, str]) -> list[dict[str, Any]]:
            book, category, market_key = task
            client = OddsClient(books=[book])
            try:
                props = client.get_props(
                    sport.lower(),
                    str(category.category_id),
                    str(category.subcategory_id) if category.subcategory_id is not None else None,
                    book=book,
                )
            except Exception:
                return []
            rows: list[dict[str, Any]] = []
            for prop in props:
                teams = _split_game(getattr(prop, "game", None))
                if teams is None:
                    # A league-wide catalog cannot safely attach a prop lacking
                    # event teams to one scheduled matchup.
                    continue
                player = str(getattr(prop, "player", "") or "").strip()
                if not player:
                    continue
                line = getattr(prop, "line", None)
                over, under = getattr(prop, "over_odds", None), getattr(prop, "under_odds", None)
                if over is None and under is None:
                    continue
                rows.append({
                    "book": book,
                    "market_key": market_key,
                    "away": teams[0],
                    "home": teams[1],
                    "player": player,
                    "line": line,
                    "over": over,
                    "under": under,
                    "fetched_at": getattr(prop, "fetched_at", None),
                })
            return rows

        catalog: list[dict[str, Any]] = []
        if selected:
            with ThreadPoolExecutor(max_workers=min(8, len(selected)), thread_name_prefix="philthy-prop-fetch") as pool:
                futures = [pool.submit(fetch_one, task) for task in selected]
                for future in as_completed(futures):
                    try:
                        catalog.extend(future.result())
                    except Exception:
                        continue
        return catalog

    return _cached_value(cache_key, _GATEWAY_CACHE_TTL_SECONDS, build)


def _oddswrap_prop_event(sport: str, game: dict[str, Any], requested_markets: list[str]) -> dict[str, Any] | None:
    observed = datetime.now(timezone.utc).isoformat()
    by_book: dict[str, dict[str, Any]] = {}
    for prop in _oddswrap_prop_catalog(sport, requested_markets):
        if not (
            _same_team(prop.get("away"), game.get("away"))
            and _same_team(prop.get("home"), game.get("home"))
        ):
            continue
        outcomes = []
        if prop.get("over") is not None:
            outcomes.append({
                "name": "Over", "description": prop["player"],
                "point": prop.get("line"), "price": prop["over"],
            })
        if prop.get("under") is not None:
            outcomes.append({
                "name": "Under", "description": prop["player"],
                "point": prop.get("line"), "price": prop["under"],
            })
        if not outcomes:
            continue
        book_name = str(prop.get("book") or "").strip()
        if not book_name:
            continue
        book_row = by_book.setdefault(book_name, {
            "key": book_name, "title": book_name, "observed_at": observed, "markets": []
        })
        book_row["markets"].append({
            "key": prop["market_key"],
            "observed_at": prop.get("fetched_at") or observed,
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
''',
        "cached parallel oddswrap props",
    )

    replace_once(
        GATEWAY,
        '''        "event_match_tolerance_seconds": 1800,
        "oddswrap": {"available": oddswrap_available, "books": oddswrap_books},''',
        '''        "event_match_tolerance_seconds": 1800,
        "latency_controls": {
            "cache_ttl_seconds": _GATEWAY_CACHE_TTL_SECONDS,
            "oddswrap_game_market_families_parallel": True,
            "oddswrap_prop_catalog_cached": True,
            "oddswrap_prop_discovery_parallel": True,
            "sx_timeout_seconds": _SX_TIMEOUT_SECONDS,
            "sx_parallel_with_verification": True,
        },
        "oddswrap": {"available": oddswrap_available, "books": oddswrap_books},''',
        "gateway latency status",
    )


def patch_app() -> None:
    replace_once(APP, 'APP_VERSION = "1.6.11"', 'APP_VERSION = "1.6.12"', "backend version")


def patch_tests() -> None:
    text = TESTS.read_text(encoding="utf-8")
    marker = "def test_cached_value_reuses_provider_result"
    if marker in text:
        return
    text += '''


def test_cached_value_reuses_provider_result():
    gateway._GATEWAY_CACHE.clear()
    calls = {"count": 0}

    def factory():
        calls["count"] += 1
        return ["value"]

    assert gateway._cached_value(("test-cache",), 60, factory) == ["value"]
    assert gateway._cached_value(("test-cache",), 60, factory) == ["value"]
    assert calls["count"] == 1


def test_prop_catalog_is_filtered_to_requested_game(monkeypatch):
    monkeypatch.setattr(gateway, "_oddswrap_prop_catalog", lambda sport, markets: [
        {
            "book": "draftkings", "market_key": "player_pass_yds",
            "away": "Away A", "home": "Home A", "player": "Player A",
            "line": 249.5, "over": -110, "under": -110, "fetched_at": None,
        },
        {
            "book": "fanduel", "market_key": "player_pass_yds",
            "away": "Away B", "home": "Home B", "player": "Player B",
            "line": 249.5, "over": -105, "under": -115, "fetched_at": None,
        },
    ])
    game = {
        "event_id": "a", "away": "Away A", "home": "Home A",
        "event_time": (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat(),
    }
    event = gateway._oddswrap_prop_event("NFL", game, ["player_pass_yds"])
    assert event is not None
    assert [book["key"] for book in event["bookmakers"]] == ["draftkings"]
    assert event["bookmakers"][0]["markets"][0]["outcomes"][0]["description"] == "Player A"
'''
    TESTS.write_text(text, encoding="utf-8")


def patch_docs() -> None:
    text = DOCS.read_text(encoding="utf-8")
    marker = "## Latency hardening — 1.6.12"
    if marker in text:
        return
    text += '''

## Latency hardening — 1.6.12

The FreeOddsGateway now caches short-lived read-only provider results, fetches oddswrap moneyline/spread/total families concurrently, runs SX Bet secondary evidence in parallel with primary multi-book verification, and limits SX read timeouts. Player-prop discovery is built once per sport/requested-market set, with sportsbook discovery and category fetches parallelized and the resulting league catalog reused while scanning scheduled games.

These controls preserve fail-closed semantics: timeout/fetch failures reduce verified coverage rather than inventing a line. They specifically remove the repeated provider fan-out that caused Best 12, Best 3, and 7/10/14-leg board routes to exceed the portable API contract timeout.
'''
    DOCS.write_text(text, encoding="utf-8")


def main() -> None:
    patch_gateway()
    patch_app()
    patch_tests()
    patch_docs()
    print("FreeOddsGateway latency optimization applied")


if __name__ == "__main__":
    main()
