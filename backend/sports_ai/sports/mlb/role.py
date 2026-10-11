from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any

import requests


def _utc(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _num(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if result == result and result not in (float("inf"), float("-inf")) else 0.0


def _avg(values: list[float]) -> float | None:
    return mean(values) if values else None


def _round(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


def _team_matches(team: dict[str, Any] | None, target: str | int) -> bool:
    if not isinstance(team, dict):
        return False
    target_text = str(target)
    if target_text.isdigit() and str(team.get("id") or "") == target_text:
        return True
    wanted = "".join(ch for ch in target_text.lower() if ch.isalnum())
    candidate = "".join(ch for ch in str(team.get("name") or team.get("teamName") or "").lower() if ch.isalnum())
    return bool(wanted and candidate and (wanted == candidate or wanted in candidate or candidate in wanted))


def _normalize_feed(raw: dict[str, Any]) -> dict[str, Any]:
    game_data = raw.get("gameData") if isinstance(raw.get("gameData"), dict) else {}
    live_data = raw.get("liveData") if isinstance(raw.get("liveData"), dict) else {}
    boxscore = live_data.get("boxscore") if isinstance(live_data.get("boxscore"), dict) else {}
    players_by_id = game_data.get("players") if isinstance(game_data.get("players"), dict) else {}

    def side(which: str) -> dict[str, Any]:
        game_team = game_data.get("teams", {}).get(which, {}) if isinstance(game_data.get("teams"), dict) else {}
        box_team = boxscore.get("teams", {}).get(which, {}) if isinstance(boxscore.get("teams"), dict) else {}
        order = box_team.get("battingOrder") if isinstance(box_team.get("battingOrder"), list) else []
        order_ids = [str(value) for value in order]
        player_rows = box_team.get("players") if isinstance(box_team.get("players"), dict) else {}
        hitters: list[dict[str, Any]] = []
        for key, row in player_rows.items():
            if not isinstance(row, dict):
                continue
            person = row.get("person") if isinstance(row.get("person"), dict) else {}
            player_id = str(person.get("id") or str(key).removeprefix("ID") or "")
            fallback = players_by_id.get(f"ID{player_id}") if isinstance(players_by_id.get(f"ID{player_id}"), dict) else {}
            name = str(person.get("fullName") or fallback.get("fullName") or "").strip()
            batting = row.get("stats", {}).get("batting", {}) if isinstance(row.get("stats"), dict) and isinstance(row.get("stats", {}).get("batting"), dict) else {}
            try:
                lineup_slot = order_ids.index(player_id) + 1
            except ValueError:
                lineup_slot = None
            plate_appearances = _num(batting.get("plateAppearances"))
            if plate_appearances <= 0 and lineup_slot is None:
                continue
            hitters.append(
                {
                    "personId": player_id,
                    "name": name,
                    "lineupSlot": lineup_slot,
                    "plateAppearances": plate_appearances,
                    "atBats": _num(batting.get("atBats")),
                    "hits": _num(batting.get("hits")),
                    "baseOnBalls": _num(batting.get("baseOnBalls")),
                    "strikeOuts": _num(batting.get("strikeOuts")),
                    "homeRuns": _num(batting.get("homeRuns")),
                    "totalBases": _num(batting.get("totalBases")),
                    "rbi": _num(batting.get("rbi")),
                    "runs": _num(batting.get("runs")),
                }
            )
        return {
            "id": game_team.get("id"),
            "name": game_team.get("name"),
            "battingOrder": order_ids,
            "hitters": hitters,
        }

    status = game_data.get("status") if isinstance(game_data.get("status"), dict) else {}
    dt = game_data.get("datetime") if isinstance(game_data.get("datetime"), dict) else {}
    return {
        "gamePk": str(game_data.get("game", {}).get("pk") or "") if isinstance(game_data.get("game"), dict) else "",
        "gameDate": dt.get("dateTime"),
        "gameStatusText": status.get("abstractGameState") or status.get("detailedState"),
        "homeTeam": side("home"),
        "awayTeam": side("away"),
    }


def summarize_team_role(team: str | int, games: list[dict[str, Any]], target_event_time: str) -> dict[str, Any]:
    """Summarize rolling plate appearances from completed games before first pitch."""

    target = _utc(target_event_time)
    if target is None:
        raise ValueError("target_event_time must be a valid timestamp")
    samples: dict[str, dict[str, Any]] = {}
    accepted_games: list[str] = []
    chronological: list[tuple[datetime, dict[str, Any]]] = []
    for game in games:
        when = _utc(game.get("gameDate"))
        if when is None or when >= target:
            continue
        if str(game.get("gameStatusText") or "").lower() != "final":
            continue
        chronological.append((when, game))
    chronological.sort(key=lambda row: row[0])

    for when, game in chronological:
        home = game.get("homeTeam") if isinstance(game.get("homeTeam"), dict) else None
        away = game.get("awayTeam") if isinstance(game.get("awayTeam"), dict) else None
        team_row = home if _team_matches(home, team) else away if _team_matches(away, team) else None
        if team_row is None:
            continue
        game_pk = str(game.get("gamePk") or "")
        accepted_games.append(game_pk)
        hitters = team_row.get("hitters") if isinstance(team_row.get("hitters"), list) else []
        for hitter in hitters:
            if not isinstance(hitter, dict):
                continue
            player_id = str(hitter.get("personId") or hitter.get("name") or "")
            name = str(hitter.get("name") or "").strip()
            if not player_id or not name:
                continue
            entry = samples.setdefault(player_id, {"player_id": player_id, "player": name, "rows": []})
            entry["rows"].append(
                {
                    "game_pk": game_pk,
                    "game_time_utc": when.isoformat(),
                    "lineup_slot": hitter.get("lineupSlot"),
                    "plate_appearances": _num(hitter.get("plateAppearances")),
                    "at_bats": _num(hitter.get("atBats")),
                    "hits": _num(hitter.get("hits")),
                    "walks": _num(hitter.get("baseOnBalls")),
                    "strikeouts": _num(hitter.get("strikeOuts")),
                    "home_runs": _num(hitter.get("homeRuns")),
                    "total_bases": _num(hitter.get("totalBases")),
                    "rbi": _num(hitter.get("rbi")),
                    "runs": _num(hitter.get("runs")),
                }
            )

    sample_games = len(set(accepted_games))
    output: list[dict[str, Any]] = []
    for entry in samples.values():
        rows = sorted(entry.pop("rows"), key=lambda row: row["game_time_utc"])
        pas = [float(row["plate_appearances"]) for row in rows]
        slots = [float(row["lineup_slot"]) for row in rows if row["lineup_slot"] is not None]
        starts = sum(1 for row in rows if row["lineup_slot"] is not None)
        output.append(
            {
                **entry,
                "games": len(rows),
                "starts": starts,
                "start_rate": _round(starts / sample_games, 3) if sample_games else None,
                "average_plate_appearances": _round(_avg(pas), 2),
                "last_three_plate_appearances": _round(_avg(pas[-3:]), 2),
                "average_lineup_slot": _round(_avg(slots), 2),
                "average_hits": _round(_avg([float(row["hits"]) for row in rows]), 2),
                "average_walks": _round(_avg([float(row["walks"]) for row in rows]), 2),
                "average_strikeouts": _round(_avg([float(row["strikeouts"]) for row in rows]), 2),
                "average_home_runs": _round(_avg([float(row["home_runs"]) for row in rows]), 3),
                "average_total_bases": _round(_avg([float(row["total_bases"]) for row in rows]), 2),
                "average_rbi": _round(_avg([float(row["rbi"]) for row in rows]), 2),
                "average_runs": _round(_avg([float(row["runs"]) for row in rows]), 2),
                "plate_appearance_sample": rows,
            }
        )
    output.sort(key=lambda row: (-(row.get("average_lineup_slot") or 99), row.get("average_plate_appearances") or 0), reverse=True)
    return {
        "team": str(team),
        "games_used": list(dict.fromkeys(accepted_games)),
        "sample_games": sample_games,
        "hitters": output,
    }


def extract_target_state(raw_feed: dict[str, Any]) -> dict[str, Any]:
    """Extract currently posted lineup and probable pitchers from a target-game feed."""

    game_data = raw_feed.get("gameData") if isinstance(raw_feed.get("gameData"), dict) else {}
    live_data = raw_feed.get("liveData") if isinstance(raw_feed.get("liveData"), dict) else {}
    boxscore = live_data.get("boxscore") if isinstance(live_data.get("boxscore"), dict) else {}
    players = game_data.get("players") if isinstance(game_data.get("players"), dict) else {}
    probable = game_data.get("probablePitchers") if isinstance(game_data.get("probablePitchers"), dict) else {}

    def lineup(which: str) -> dict[str, Any]:
        box_team = boxscore.get("teams", {}).get(which, {}) if isinstance(boxscore.get("teams"), dict) else {}
        order = box_team.get("battingOrder") if isinstance(box_team.get("battingOrder"), list) else []
        rows = []
        for slot, player_id in enumerate(order, start=1):
            player = players.get(f"ID{player_id}") if isinstance(players.get(f"ID{player_id}"), dict) else {}
            rows.append({"slot": slot, "player_id": str(player_id), "player": player.get("fullName")})
        return {
            "status": "POSTED" if len(rows) >= 9 else "UNAVAILABLE_NOT_POSTED",
            "confirmed": len(rows) >= 9,
            "batting_order": rows,
        }

    def pitcher(which: str) -> dict[str, Any]:
        row = probable.get(which) if isinstance(probable.get(which), dict) else {}
        return {
            "status": "PROBABLE" if row.get("id") or row.get("fullName") else "UNAVAILABLE",
            "player_id": str(row.get("id") or "") or None,
            "player": row.get("fullName"),
        }

    return {
        "home_lineup": lineup("home"),
        "away_lineup": lineup("away"),
        "home_probable_pitcher": pitcher("home"),
        "away_probable_pitcher": pitcher("away"),
    }


def _response_json(session: requests.Session, url: str, *, params: dict[str, Any] | None = None) -> Any:
    response = session.get(url, params=params, headers={"Accept": "application/json"}, timeout=(3, 15))
    response.raise_for_status()
    return response.json()


def fetch_mlb_role_context(
    event: dict[str, Any],
    *,
    session: requests.Session | None = None,
    lookback_games: int = 5,
) -> dict[str, Any]:
    """Fetch MLB posted-lineup/probable-pitcher state and rolling PA context."""

    target = _utc(event.get("commence_time") or event.get("event_time"))
    now = datetime.now(timezone.utc)
    event_id = str(event.get("id") or event.get("event_id") or "")
    if target is None or target <= now:
        return {"status": "NOT_PREGAME", "sport": "MLB", "event_id": event_id, "model_influence": False}
    try:
        game_pk = int(event_id)
    except ValueError:
        return {"status": "TARGET_EVENT_ID_NOT_MLB_GAME_PK", "sport": "MLB", "event_id": event_id, "model_influence": False}

    client = session or requests.Session()
    target_feed = _response_json(client, f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live")
    target_state = extract_target_state(target_feed)
    game_data = target_feed.get("gameData") if isinstance(target_feed.get("gameData"), dict) else {}
    teams = game_data.get("teams") if isinstance(game_data.get("teams"), dict) else {}
    home_team = teams.get("home") if isinstance(teams.get("home"), dict) else {}
    away_team = teams.get("away") if isinstance(teams.get("away"), dict) else {}
    home_id = home_team.get("id")
    away_id = away_team.get("id")
    if home_id is None or away_id is None:
        raise ValueError("MLB target feed is missing team ids")

    start_date = (target.date() - timedelta(days=30)).isoformat()
    end_date = (target.date() - timedelta(days=1)).isoformat()

    def recent_ids(team_id: int) -> list[str]:
        payload = _response_json(
            client,
            "https://statsapi.mlb.com/api/v1/schedule",
            params={
                "sportId": 1,
                "teamId": team_id,
                "startDate": start_date,
                "endDate": end_date,
            },
        )
        rows: list[tuple[datetime, str]] = []
        dates = payload.get("dates") if isinstance(payload, dict) and isinstance(payload.get("dates"), list) else []
        for day in dates:
            games = day.get("games") if isinstance(day, dict) and isinstance(day.get("games"), list) else []
            for game in games:
                if not isinstance(game, dict):
                    continue
                when = _utc(game.get("gameDate"))
                status = game.get("status") if isinstance(game.get("status"), dict) else {}
                if when is None or when >= target or str(status.get("abstractGameState") or "").lower() != "final":
                    continue
                game_id = str(game.get("gamePk") or "")
                if game_id:
                    rows.append((when, game_id))
        rows.sort(reverse=True)
        return [game_id for _, game_id in rows[:lookback_games]]

    game_ids = list(dict.fromkeys(recent_ids(int(home_id)) + recent_ids(int(away_id))))
    historical: list[dict[str, Any]] = []
    failures = 0
    for historical_pk in game_ids:
        try:
            raw = _response_json(client, f"https://statsapi.mlb.com/api/v1.1/game/{historical_pk}/feed/live")
            historical.append(_normalize_feed(raw))
        except Exception:
            failures += 1

    home = summarize_team_role(int(home_id), historical, target.isoformat())
    away = summarize_team_role(int(away_id), historical, target.isoformat())
    if home["sample_games"] and away["sample_games"]:
        status = "PARTIAL_VERIFIED_CONTEXT" if failures else "VERIFIED_CONTEXT"
    else:
        status = "INSUFFICIENT_COMPLETED_GAME_CONTEXT"
    return {
        "status": status,
        "sport": "MLB",
        "event_id": event_id,
        "target_event_time": target.isoformat(),
        "source": "mlb_statsapi_live_feed_and_schedule",
        "source_health": {
            "boxscores_requested": len(game_ids),
            "boxscores_loaded": len(historical),
            "boxscores_failed": failures,
        },
        "point_in_time_rule": "historical gameDate < target_event_time and Final only",
        "target_state": target_state,
        "plate_appearance_method": "official MLB boxscore batting plateAppearances and posted battingOrder",
        "statcast": {
            "status": "UNAVAILABLE_NOT_CONNECTED",
            "xwoba": None,
            "pitch_mix": None,
            "note": "Basic MLB boxscore statistics are not relabeled as Statcast features.",
        },
        "model_influence": False,
        "promotion_policy": "context_only_until_promoted_artifact_declares_compatible_lineup_pa_or_statcast_features",
        "home": home,
        "away": away,
        "observed_at": now.isoformat(),
    }
