from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean
from typing import Any

import requests

NBA_CDN_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Origin": "https://www.nba.com",
    "Referer": "https://www.nba.com/",
    "Accept-Language": "en-US,en;q=0.9",
}


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


def _norm(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _team_matches(team: dict[str, Any] | None, target: str) -> bool:
    if not isinstance(team, dict):
        return False
    wanted = _norm(target)
    name = _norm(team.get("teamName") or team.get("name") or team.get("displayName"))
    full = _norm(f"{team.get('teamCity') or team.get('location') or ''} {team.get('teamName') or team.get('name') or ''}")
    return bool(wanted and ((full and (wanted == full or wanted in full or full in wanted)) or (name and wanted.endswith(name))))


def _num(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if result == result and result not in (float("inf"), float("-inf")) else 0.0


def _minutes(value: Any) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    raw = str(value or "").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    if not raw.upper().startswith("PT"):
        return 0.0
    body = raw[2:].upper()
    hours = 0.0
    minutes = 0.0
    seconds = 0.0
    if "H" in body:
        token, body = body.split("H", 1)
        hours = _num(token)
    if "M" in body:
        token, body = body.split("M", 1)
        minutes = _num(token)
    if body.endswith("S"):
        seconds = _num(body[:-1])
    return hours * 60.0 + minutes + seconds / 60.0


def _avg(values: list[float]) -> float | None:
    return mean(values) if values else None


def _round(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


def summarize_team_role(team_name: str, games: list[dict[str, Any]], target_event_time: str) -> dict[str, Any]:
    """Summarize rolling NBA minutes and estimated usage from settled games only.

    The function is deliberately prediction-neutral. It accepts normalized NBA
    boxscore-like dictionaries and enforces game_time < target_event_time.
    """

    target = _utc(target_event_time)
    if target is None:
        raise ValueError("target_event_time must be a valid timestamp")

    players: dict[str, dict[str, Any]] = {}
    accepted_games: list[str] = []
    chronological = []
    for game in games:
        when = _utc(game.get("gameTimeUTC"))
        if when is None or when >= target:
            continue
        if str(game.get("gameStatusText") or "").lower() != "final":
            continue
        chronological.append((when, game))
    chronological.sort(key=lambda row: row[0])

    for when, game in chronological:
        home = game.get("homeTeam") if isinstance(game.get("homeTeam"), dict) else None
        away = game.get("awayTeam") if isinstance(game.get("awayTeam"), dict) else None
        team = home if _team_matches(home, team_name) else away if _team_matches(away, team_name) else None
        if team is None:
            continue
        raw_players = team.get("players") if isinstance(team.get("players"), list) else []
        active: list[tuple[dict[str, Any], float]] = []
        for player in raw_players:
            if not isinstance(player, dict):
                continue
            stats = player.get("statistics") if isinstance(player.get("statistics"), dict) else {}
            minutes = _minutes(stats.get("minutes"))
            if minutes <= 0 or str(player.get("played") or "1") == "0":
                continue
            active.append((player, minutes))
        if not active:
            continue

        def stat(player: dict[str, Any], key: str) -> float:
            stats = player.get("statistics") if isinstance(player.get("statistics"), dict) else {}
            return _num(stats.get(key))

        team_minutes = sum(minutes for _, minutes in active)
        team_fga = sum(stat(player, "fieldGoalsAttempted") for player, _ in active)
        team_fta = sum(stat(player, "freeThrowsAttempted") for player, _ in active)
        team_tov = sum(stat(player, "turnovers") for player, _ in active)
        team_actions = team_fga + 0.44 * team_fta + team_tov
        game_id = str(game.get("gameId") or "")
        accepted_games.append(game_id)

        for player, minutes in active:
            player_id = str(player.get("personId") or player.get("name") or "")
            name = str(player.get("name") or "").strip()
            if not player_id or not name:
                continue
            actions = stat(player, "fieldGoalsAttempted") + 0.44 * stat(player, "freeThrowsAttempted") + stat(player, "turnovers")
            usage = None
            if team_actions > 0 and minutes > 0:
                usage = max(0.0, min(1.0, actions * (team_minutes / 5.0) / (minutes * team_actions)))
            row = players.setdefault(
                player_id,
                {
                    "player_id": player_id,
                    "player": name,
                    "position": player.get("position") if isinstance(player.get("position"), str) else None,
                    "rows": [],
                },
            )
            row["rows"].append(
                {
                    "game_id": game_id,
                    "game_time_utc": when.isoformat(),
                    "minutes": minutes,
                    "usage_rate": usage,
                    "starter": str(player.get("starter") or "") == "1",
                    "points": stat(player, "points"),
                    "rebounds": stat(player, "reboundsTotal"),
                    "assists": stat(player, "assists"),
                }
            )

    output = []
    for entry in players.values():
        rows = sorted(entry.pop("rows"), key=lambda row: row["game_time_utc"])
        minute_values = [float(row["minutes"]) for row in rows]
        usage_values = [float(row["usage_rate"]) for row in rows if row["usage_rate"] is not None]
        recent = minute_values[-3:]
        prior = minute_values[:-3]
        recent_avg = _avg(recent)
        prior_avg = _avg(prior)
        output.append(
            {
                **entry,
                "games": len(rows),
                "average_minutes": _round(_avg(minute_values), 2),
                "last_three_minutes": _round(recent_avg, 2),
                "minutes_trend": _round(recent_avg - prior_avg, 2) if recent_avg is not None and prior_avg is not None else None,
                "average_usage_rate": _round(_avg(usage_values), 4),
                "starter_rate": _round(sum(1 for row in rows if row["starter"]) / len(rows), 3),
                "average_points": _round(_avg([float(row["points"]) for row in rows]), 2),
                "average_rebounds": _round(_avg([float(row["rebounds"]) for row in rows]), 2),
                "average_assists": _round(_avg([float(row["assists"]) for row in rows]), 2),
                "last_game_minutes": _round(float(rows[-1]["minutes"]), 2),
                "role_sample": rows,
            }
        )
    output.sort(key=lambda row: row.get("last_three_minutes") or row.get("average_minutes") or 0.0, reverse=True)
    return {
        "team": team_name,
        "games_used": list(dict.fromkeys(accepted_games)),
        "sample_games": len(set(accepted_games)),
        "players": output,
    }


def _response_json(session: requests.Session, url: str, *, headers: dict[str, str] | None = None, params: dict[str, Any] | None = None) -> Any:
    response = session.get(url, headers=headers, params=params, timeout=(3, 12))
    response.raise_for_status()
    return response.json()


def _recent_cdn_ids(games: list[dict[str, Any]], team: str, target: datetime, limit: int = 5) -> list[str]:
    rows = []
    for game in games:
        when = _utc(game.get("gameDateTimeUTC"))
        if when is None or when >= target:
            continue
        if int(game.get("gameStatus") or 0) != 3 and str(game.get("gameStatusText") or "").lower() != "final":
            continue
        home = game.get("homeTeam") if isinstance(game.get("homeTeam"), dict) else None
        away = game.get("awayTeam") if isinstance(game.get("awayTeam"), dict) else None
        if not (_team_matches(home, team) or _team_matches(away, team)):
            continue
        rows.append((when, str(game.get("gameId") or "")))
    rows.sort(reverse=True)
    return [game_id for _, game_id in rows[:limit] if game_id]


def _espn_team_matches(event: dict[str, Any], target: str) -> bool:
    comps = event.get("competitions") if isinstance(event.get("competitions"), list) else []
    competitors = comps[0].get("competitors") if comps and isinstance(comps[0], dict) and isinstance(comps[0].get("competitors"), list) else []
    wanted = _norm(target)
    for row in competitors:
        team = row.get("team") if isinstance(row, dict) and isinstance(row.get("team"), dict) else {}
        display = _norm(team.get("displayName"))
        name = _norm(team.get("name"))
        if wanted and ((display and (wanted == display or wanted in display or display in wanted)) or (name and wanted.endswith(name))):
            return True
    return False


def _espn_attempts(value: Any) -> float:
    token = str(value or "0-0").split("-")[-1]
    return _num(token)


def _normalize_espn_team(group: dict[str, Any]) -> dict[str, Any]:
    blocks = group.get("statistics") if isinstance(group.get("statistics"), list) else []
    block = blocks[0] if blocks and isinstance(blocks[0], dict) else {}
    keys = [str(key) for key in block.get("keys", [])] if isinstance(block.get("keys"), list) else []
    athletes = block.get("athletes") if isinstance(block.get("athletes"), list) else []

    def value(stats: list[Any], key: str) -> Any:
        try:
            return stats[keys.index(key)]
        except (ValueError, IndexError):
            return None

    normalized_players = []
    for row in athletes:
        if not isinstance(row, dict):
            continue
        athlete = row.get("athlete") if isinstance(row.get("athlete"), dict) else {}
        stats = row.get("stats") if isinstance(row.get("stats"), list) else []
        position = athlete.get("position") if isinstance(athlete.get("position"), dict) else {}
        normalized_players.append(
            {
                "personId": str(athlete.get("id") or ""),
                "name": str(athlete.get("displayName") or ""),
                "position": position.get("abbreviation"),
                "starter": "1" if row.get("starter") is True else "0",
                "played": "0" if row.get("didNotPlay") is True else "1",
                "statistics": {
                    "minutes": value(stats, "minutes"),
                    "fieldGoalsAttempted": _espn_attempts(value(stats, "fieldGoalsMade-fieldGoalsAttempted")),
                    "freeThrowsAttempted": _espn_attempts(value(stats, "freeThrowsMade-freeThrowsAttempted")),
                    "turnovers": _num(value(stats, "turnovers")),
                    "points": _num(value(stats, "points")),
                    "reboundsTotal": _num(value(stats, "rebounds")),
                    "assists": _num(value(stats, "assists")),
                },
            }
        )
    team = group.get("team") if isinstance(group.get("team"), dict) else {}
    return {"teamName": str(team.get("displayName") or team.get("name") or ""), "teamCity": "", "players": normalized_players}


def _fetch_espn_fallback(session: requests.Session, event: dict[str, Any], target: datetime, limit: int) -> tuple[list[dict[str, Any]], str, int, int]:
    previous_month = target.month - 1 or 12
    previous_year = target.year - 1 if target.month == 1 else target.year
    month_keys = [f"{previous_year:04d}{previous_month:02d}", f"{target.year:04d}{target.month:02d}"]
    by_id: dict[str, dict[str, Any]] = {}
    season = str(target.year)
    for month in dict.fromkeys(month_keys):
        payload = _response_json(
            session,
            "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
            params={"dates": month, "limit": 1000},
        )
        leagues = payload.get("leagues") if isinstance(payload, dict) and isinstance(payload.get("leagues"), list) else []
        if leagues and isinstance(leagues[0], dict) and isinstance(leagues[0].get("season"), dict):
            season = str(leagues[0]["season"].get("year") or season)
        for row in payload.get("events", []) if isinstance(payload, dict) and isinstance(payload.get("events"), list) else []:
            if isinstance(row, dict) and row.get("id"):
                by_id[str(row["id"])] = row

    def ids_for(team: str) -> list[str]:
        candidates = []
        for row in by_id.values():
            when = _utc(row.get("date"))
            status = row.get("status") if isinstance(row.get("status"), dict) else {}
            status_type = status.get("type") if isinstance(status.get("type"), dict) else {}
            if when is None or when >= target or (status_type.get("completed") is not True and str(status_type.get("state") or "").lower() != "post"):
                continue
            if _espn_team_matches(row, team):
                candidates.append((when, str(row.get("id"))))
        candidates.sort(reverse=True)
        return [game_id for _, game_id in candidates[:limit]]

    game_ids = list(dict.fromkeys(ids_for(str(event["home_team"])) + ids_for(str(event["away_team"]))))
    boxes: list[dict[str, Any]] = []
    failures = 0
    for game_id in game_ids:
        try:
            payload = _response_json(
                session,
                "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary",
                params={"event": game_id},
            )
            box = payload.get("boxscore") if isinstance(payload, dict) and isinstance(payload.get("boxscore"), dict) else {}
            groups = box.get("players") if isinstance(box.get("players"), list) else []
            if len(groups) < 2 or not all(isinstance(group, dict) for group in groups[:2]):
                raise ValueError("ESPN NBA summary did not contain player boxscore groups")
            source_event = by_id[game_id]
            boxes.append(
                {
                    "gameId": game_id,
                    "gameTimeUTC": source_event.get("date"),
                    "gameStatusText": "Final",
                    "homeTeam": _normalize_espn_team(groups[0]),
                    "awayTeam": _normalize_espn_team(groups[1]),
                }
            )
        except Exception:
            failures += 1
    return boxes, season, len(game_ids), failures


def fetch_nba_role_context(event: dict[str, Any], *, session: requests.Session | None = None, lookback_games: int = 5) -> dict[str, Any]:
    """Fetch point-in-time NBA role context without allowing it to affect probabilities.

    NBA CDN is primary. ESPN Site API is an explicit fallback for environments
    where the NBA CDN blocks the server IP. Both paths use only final games that
    started before the target event.
    """

    target = _utc(event.get("commence_time") or event.get("event_time"))
    now = datetime.now(timezone.utc)
    if target is None or target <= now:
        return {
            "status": "NOT_PREGAME",
            "sport": "NBA",
            "event_id": str(event.get("id") or event.get("event_id") or ""),
            "model_influence": False,
        }
    client = session or requests.Session()
    source = "nba_cdn_scheduleLeagueV2_liveData_boxscore"
    primary_error = None
    boxes: list[dict[str, Any]] = []
    season = ""
    requested = 0
    failures = 0
    try:
        schedule = _response_json(client, "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json", headers=NBA_CDN_HEADERS)
        league = schedule.get("leagueSchedule") if isinstance(schedule, dict) and isinstance(schedule.get("leagueSchedule"), dict) else {}
        season = str(league.get("seasonYear") or "")
        date_rows = league.get("gameDates") if isinstance(league.get("gameDates"), list) else []
        games = [game for day in date_rows if isinstance(day, dict) for game in (day.get("games") if isinstance(day.get("games"), list) else []) if isinstance(game, dict)]
        game_ids = list(dict.fromkeys(_recent_cdn_ids(games, str(event["home_team"]), target, lookback_games) + _recent_cdn_ids(games, str(event["away_team"]), target, lookback_games)))
        requested = len(game_ids)
        for game_id in game_ids:
            try:
                payload = _response_json(client, f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json", headers=NBA_CDN_HEADERS)
                game = payload.get("game") if isinstance(payload, dict) else None
                if not isinstance(game, dict):
                    raise ValueError("NBA CDN boxscore did not contain game")
                boxes.append(game)
            except Exception:
                failures += 1
        if game_ids and not boxes:
            raise RuntimeError("NBA_CDN_BOXSCORES_UNAVAILABLE")
    except Exception as exc:
        primary_error = type(exc).__name__
        source = "espn_site_api_scoreboard_summary_fallback"
        boxes, season, requested, failures = _fetch_espn_fallback(client, event, target, lookback_games)

    home = summarize_team_role(str(event["home_team"]), boxes, target.isoformat())
    away = summarize_team_role(str(event["away_team"]), boxes, target.isoformat())
    status = "VERIFIED_CONTEXT" if home["sample_games"] and away["sample_games"] and failures == 0 else "PARTIAL_VERIFIED_CONTEXT" if home["sample_games"] and away["sample_games"] else "INSUFFICIENT_COMPLETED_GAME_CONTEXT"
    return {
        "status": status,
        "sport": "NBA",
        "event_id": str(event.get("id") or event.get("event_id") or ""),
        "target_event_time": target.isoformat(),
        "season": season,
        "source": source,
        "source_health": {
            "primary_nba_cdn": "available" if primary_error is None else "unavailable",
            "primary_error_type": primary_error,
            "fallback_used": source.startswith("espn_"),
            "boxscores_requested": requested,
            "boxscores_loaded": len(boxes),
            "boxscores_failed": failures,
        },
        "point_in_time_rule": "only final games with game_time < target_event_time",
        "usage_method": "estimated possession usage from FGA + 0.44*FTA + TOV and player minutes",
        "model_influence": False,
        "promotion_policy": "context_only_until_promoted_artifact_declares_compatible_role_features",
        "home": home,
        "away": away,
        "observed_at": now.isoformat(),
    }
