from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import re
import threading
import time
from typing import Any

from curl_cffi import requests as cffi_requests


_LEAGUE_IDS = {
    "MLB": 84240,
    "NBA": 42648,
    "NFL": 88808,
    "NHL": 42133,
}
_GAME_CATEGORY_ID = 493
_BASE = "https://sportsbook-nash.draftkings.com/api/sportscontent/dkusnj/v1"
_CACHE: dict[str, tuple[float, Any]] = {}
_LOCK = threading.Lock()


def _parse_price(value: Any) -> int | None:
    try:
        text = str(value or "").strip().replace("−", "-")
        return int(text)
    except (TypeError, ValueError):
        return None


def _norm(value: str | None) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _cached(key: str, ttl: int, fn):
    now = time.time()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] <= ttl:
            return hit[1]
    value = fn()
    with _LOCK:
        _CACHE[key] = (now, value)
    return value


def _get_json(url: str) -> dict[str, Any]:
    response = cffi_requests.get(
        url,
        impersonate="chrome120",
        headers={"Accept": "application/json"},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("DraftKings response was not a JSON object")
    return payload


def _event_teams(event: dict[str, Any]) -> tuple[str, str] | None:
    name = str(event.get("name") or "")
    if " @ " not in name:
        return None
    away, home = name.split(" @ ", 1)
    away, home = away.strip(), home.strip()
    return (away, home) if away and home else None


def _selection_price(selection: dict[str, Any]) -> int | None:
    display = selection.get("displayOdds")
    if not isinstance(display, dict):
        return None
    return _parse_price(display.get("american"))


def _game_payload(sport: str) -> dict[str, Any]:
    league = _LEAGUE_IDS[sport]
    url = f"{_BASE}/leagues/{league}/categories/{_GAME_CATEGORY_ID}"
    return _cached(f"games:{sport}", 20, lambda: _get_json(url))


def draftkings_game_events(sport: str) -> list[dict[str, Any]]:
    s = sport.upper()
    if s not in _LEAGUE_IDS:
        return []
    data = _game_payload(s)
    observed = datetime.now(timezone.utc).isoformat()
    events = {
        str(event.get("id")): event
        for event in data.get("events") or []
        if isinstance(event, dict) and event.get("id") is not None
    }
    selections_by_market: dict[str, list[dict[str, Any]]] = {}
    for selection in data.get("selections") or []:
        if not isinstance(selection, dict):
            continue
        selections_by_market.setdefault(str(selection.get("marketId")), []).append(selection)

    out: dict[str, dict[str, Any]] = {}
    for market in data.get("markets") or []:
        if not isinstance(market, dict):
            continue
        event_id = str(market.get("eventId") or "")
        event = events.get(event_id)
        if not event:
            continue
        teams = _event_teams(event)
        if not teams:
            continue
        away, home = teams
        market_name = str(market.get("name") or "").strip()
        lower = market_name.lower()
        if lower == "moneyline":
            key = "h2h"
        elif lower in {"spread", "run line", "puck line"}:
            key = "spreads"
        elif lower in {"total", "total points", "total runs", "total goals"}:
            key = "totals"
        else:
            continue

        outcomes = []
        for selection in selections_by_market.get(str(market.get("id")), []):
            price = _selection_price(selection)
            if price is None:
                continue
            label = str(selection.get("label") or "").strip()
            point = selection.get("points")
            if key == "h2h":
                if _norm(home) in _norm(label) or _norm(label) in _norm(home):
                    name = home
                elif _norm(away) in _norm(label) or _norm(label) in _norm(away):
                    name = away
                else:
                    continue
                outcomes.append({"name": name, "price": price})
            elif key == "spreads":
                if _norm(home.split()[-1]) in _norm(label) or _norm(home) in _norm(label):
                    name = home
                elif _norm(away.split()[-1]) in _norm(label) or _norm(away) in _norm(label):
                    name = away
                else:
                    continue
                try:
                    point_value = float(point)
                except (TypeError, ValueError):
                    continue
                outcomes.append({"name": name, "price": price, "point": point_value})
            else:
                ll = label.lower()
                if "over" in ll:
                    name = "Over"
                elif "under" in ll:
                    name = "Under"
                else:
                    continue
                try:
                    point_value = float(point)
                except (TypeError, ValueError):
                    continue
                outcomes.append({"name": name, "price": price, "point": point_value})

        if len(outcomes) < 2:
            continue
        row = out.setdefault(
            event_id,
            {
                "id": event_id,
                "home_team": home,
                "away_team": away,
                "commence_time": event.get("startEventDate"),
                "bookmakers": [{
                    "key": "draftkings",
                    "title": "DraftKings",
                    "observed_at": observed,
                    "markets": [],
                }],
                "market_source": "DRAFTKINGS_KEYLESS_DIRECT",
                "data_quality": "PREGAME_FETCH_OBSERVED",
            },
        )
        row["bookmakers"][0]["markets"].append(
            {
                "key": key,
                "observed_at": observed,
                "outcomes": outcomes,
            }
        )

    return list(out.values())


_PROP_MAP: dict[str, list[tuple[str, str]]] = {
    "NFL": [
        ("passrushreceptionyards", "player_pass_rush_reception_yds"),
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
        ("longestpassingcompletion", "player_pass_longest_completion"),
        ("longestreception", "player_reception_longest"),
        ("longestrush", "player_rush_longest"),
        ("sacks", "player_sacks"),
        ("solotackles", "player_solo_tackles"),
        ("tacklesassists", "player_tackles_assists"),
        ("anytimetouchdown", "player_tds"),
    ],
    "NBA": [
        ("pointsreboundsassists", "player_points_rebounds_assists"),
        ("pointsrebounds", "player_points_rebounds"),
        ("pointsassists", "player_points_assists"),
        ("reboundsassists", "player_rebounds_assists"),
        ("threepointers", "player_threes"),
        ("3pointers", "player_threes"),
        ("blockssteals", "player_blocks_steals"),
        ("points", "player_points"),
        ("rebounds", "player_rebounds"),
        ("assists", "player_assists"),
        ("blocks", "player_blocks"),
        ("steals", "player_steals"),
        ("turnovers", "player_turnovers"),
        ("freethrowsmade", "player_frees_made"),
        ("fieldgoalsmade", "player_field_goals"),
    ],
    "MLB": [
        ("pitcherstrikeouts", "pitcher_strikeouts"),
        ("pitcherouts", "pitcher_outs"),
        ("pitcherhitsallowed", "pitcher_hits_allowed"),
        ("pitcherwalks", "pitcher_walks"),
        ("pitcherearnedruns", "pitcher_earned_runs"),
        ("homeruns", "batter_home_runs"),
        ("totalbases", "batter_total_bases"),
        ("hitsrunsrbis", "batter_hits_runs_rbis"),
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
        ("goalscorer", "player_goals"),
        ("goalie saves", "player_total_saves"),
        ("goaliesaves", "player_total_saves"),
        ("saves", "player_total_saves"),
        ("points", "player_points"),
        ("assists", "player_assists"),
        ("goals", "player_goals"),
    ],
}


def _prop_key(sport: str, *names: str) -> str | None:
    combined = _norm(" ".join(names))
    # Category labels commonly insert generic words between the player role and
    # the actual statistic (for example "Pitcher Props" + "Strikeouts O/U").
    # Remove only structural labels; never rewrite the statistic itself.
    for structural in ("playerprops", "pitcherprops", "batterprops", "props", "overunder", "ou"):
        combined = combined.replace(structural, "")
    candidates = _PROP_MAP.get(sport, [])
    for needle, key in candidates:
        normalized = _norm(needle)
        for structural in ("playerprops", "pitcherprops", "batterprops", "props", "overunder", "ou"):
            normalized = normalized.replace(structural, "")
        if normalized and normalized in combined:
            return key
    return None


def _prop_catalog(sport: str) -> list[dict[str, str]]:
    league = _LEAGUE_IDS[sport]
    data = _cached(
        f"catalog:{sport}",
        300,
        lambda: _get_json(f"{_BASE}/leagues/{league}"),
    )
    categories = {
        str(row.get("id")): str(row.get("name") or "")
        for row in data.get("categories") or []
        if isinstance(row, dict) and row.get("id") is not None
    }
    out: list[dict[str, str]] = []
    for sub in data.get("subcategories") or []:
        if not isinstance(sub, dict):
            continue
        category_id = str(sub.get("categoryId") or "")
        sub_id = str(sub.get("id") or "")
        if not category_id or not sub_id:
            continue
        category_name = categories.get(category_id, "")
        sub_name = str(sub.get("name") or "")
        key = _prop_key(sport, category_name, sub_name)
        if not key:
            continue
        out.append({
            "category_id": category_id,
            "subcategory_id": sub_id,
            "category_name": category_name,
            "subcategory_name": sub_name,
            "market_key": key,
        })
    # Preserve discovery order and cap network fan-out.
    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in out:
        ident = (row["category_id"], row["subcategory_id"])
        if ident in seen:
            continue
        seen.add(ident)
        unique.append(row)
    return unique[:18]


def _strip_player(market_name: str, category_name: str, sub_name: str) -> str:
    player = market_name.strip()
    for phrase in sorted(
        {category_name.strip(), sub_name.strip(), "O/U", "Over/Under"},
        key=len,
        reverse=True,
    ):
        if not phrase:
            continue
        player = re.sub(re.escape(phrase), "", player, flags=re.IGNORECASE).strip(" -:|")
    return player.strip()


def _fetch_prop_subcategory(sport: str, row: dict[str, str]) -> list[dict[str, Any]]:
    league = _LEAGUE_IDS[sport]
    url = (
        f"{_BASE}/leagues/{league}/categories/{row['category_id']}"
        f"/subcategories/{row['subcategory_id']}"
    )
    data = _get_json(url)
    observed = datetime.now(timezone.utc).isoformat()
    events = {
        str(event.get("id")): event
        for event in data.get("events") or []
        if isinstance(event, dict) and event.get("id") is not None
    }
    selections_by_market: dict[str, list[dict[str, Any]]] = {}
    for selection in data.get("selections") or []:
        if isinstance(selection, dict):
            selections_by_market.setdefault(str(selection.get("marketId")), []).append(selection)

    results: list[dict[str, Any]] = []
    for market in data.get("markets") or []:
        if not isinstance(market, dict):
            continue
        event_id = str(market.get("eventId") or "")
        event = events.get(event_id)
        teams = _event_teams(event or {})
        if not event or not teams:
            continue
        away, home = teams
        player = _strip_player(
            str(market.get("name") or ""),
            row["category_name"],
            row["subcategory_name"],
        )
        if not player or len(player) < 2:
            continue

        selections = selections_by_market.get(str(market.get("id")), [])
        outcomes: list[dict[str, Any]] = []
        threshold_found = False
        for selection in selections:
            label = str(selection.get("label") or "").strip()
            match = re.fullmatch(r"(\d+)\+", label)
            if not match:
                continue
            price = _selection_price(selection)
            if price is None:
                continue
            threshold_found = True
            outcomes.append({
                "name": "Yes",
                "description": player,
                "point": int(match.group(1)) - 0.5,
                "price": price,
            })

        if not threshold_found:
            for selection in selections:
                price = _selection_price(selection)
                if price is None:
                    continue
                label = str(selection.get("label") or "").strip()
                lower = label.lower()
                if "over" in lower:
                    side = "Over"
                elif "under" in lower:
                    side = "Under"
                else:
                    continue
                try:
                    point = float(selection.get("points"))
                except (TypeError, ValueError):
                    continue
                outcomes.append({
                    "name": side,
                    "description": player,
                    "point": point,
                    "price": price,
                })

        if outcomes:
            results.append({
                "event_id": event_id,
                "home_team": home,
                "away_team": away,
                "commence_time": event.get("startEventDate"),
                "market_key": row["market_key"],
                "observed_at": observed,
                "outcomes": outcomes,
            })
    return results


def _draftkings_prop_events_uncached(
    sport: str,
    requested_markets: list[str] | None = None,
) -> list[dict[str, Any]]:
    s = sport.upper()
    if s not in _LEAGUE_IDS:
        return []
    wanted = set(requested_markets or [])
    catalog = [
        row
        for row in _prop_catalog(s)
        if not wanted or row["market_key"] in wanted
    ]
    if not catalog:
        return []

    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(6, len(catalog))) as pool:
        futures = [pool.submit(_fetch_prop_subcategory, s, row) for row in catalog]
        for future in futures:
            try:
                rows.extend(future.result())
            except Exception:
                continue

    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        event_id = row["event_id"]
        event = grouped.setdefault(
            event_id,
            {
                "id": event_id,
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "commence_time": row["commence_time"],
                "bookmakers": [{
                    "key": "draftkings",
                    "title": "DraftKings",
                    "observed_at": row["observed_at"],
                    "markets": [],
                }],
                "market_source": "DRAFTKINGS_KEYLESS_DIRECT",
                "data_quality": "PREGAME_FETCH_OBSERVED",
            },
        )
        event["bookmakers"][0]["markets"].append({
            "key": row["market_key"],
            "observed_at": row["observed_at"],
            "outcomes": row["outcomes"],
        })
    return list(grouped.values())


def draftkings_prop_events(
    sport: str,
    requested_markets: list[str] | None = None,
) -> list[dict[str, Any]]:
    s = sport.upper()
    wanted = sorted(set(requested_markets or []))
    key = f"props:{s}:{','.join(wanted)}"
    return _cached(
        key,
        30,
        lambda: _draftkings_prop_events_uncached(s, wanted),
    )


def keyless_sportsbook_status() -> dict[str, Any]:
    return {
        "provider": "DraftKings direct public web API",
        "credential_required": False,
        "sports": sorted(_LEAGUE_IDS),
        "game_markets": ["h2h", "spreads", "totals"],
        "props": True,
        "freshness_basis": "fresh_fetch_observed_at",
        "note": (
            "This fallback uses read-only public sportsbook responses and never embeds "
            "a user credential. Provider timestamps remain distinguished from local "
            "fetch-observation timestamps."
        ),
    }
