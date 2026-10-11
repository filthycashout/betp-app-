from __future__ import annotations

from datetime import datetime, timezone
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


def _norm(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


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


def _toi_minutes(value: Any) -> float:
    raw = str(value or "").strip()
    if not raw or ":" not in raw:
        return 0.0
    minutes, seconds = raw.split(":", 1)
    try:
        return max(0.0, float(minutes) + float(seconds) / 60.0)
    except ValueError:
        return 0.0


def _name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("default") or value.get("en") or "").strip()
    return str(value or "").strip()


def _team_matches(team: dict[str, Any] | None, target: str) -> bool:
    if not isinstance(team, dict):
        return False
    wanted = _norm(target)
    candidates = [
        _norm(team.get("abbrev")),
        _norm(team.get("teamName")),
        _norm(team.get("name")),
    ]
    return bool(wanted and any(candidate and (candidate == wanted or candidate in wanted or wanted in candidate) for candidate in candidates))


def summarize_team_role(team: str, games: list[dict[str, Any]], target_event_time: str) -> dict[str, Any]:
    """Summarize historical NHL goalie workload and skater shot role.

    Only completed games strictly before the target event are accepted. Historical
    NHL boxscore `starter` flags are retained as historical evidence; they do not
    constitute confirmation of the upcoming game's starter.
    """

    target = _utc(target_event_time)
    if target is None:
        raise ValueError("target_event_time must be a valid timestamp")

    goalie_samples: dict[str, dict[str, Any]] = {}
    skater_samples: dict[str, dict[str, Any]] = {}
    accepted_games: list[str] = []
    chronological: list[tuple[datetime, dict[str, Any]]] = []
    for game in games:
        when = _utc(game.get("gameTimeUTC"))
        if when is None or when >= target:
            continue
        if str(game.get("gameStatusText") or "").upper() not in {"FINAL", "OFF"}:
            continue
        chronological.append((when, game))
    chronological.sort(key=lambda row: row[0])

    for when, game in chronological:
        home = game.get("homeTeam") if isinstance(game.get("homeTeam"), dict) else None
        away = game.get("awayTeam") if isinstance(game.get("awayTeam"), dict) else None
        team_row = home if _team_matches(home, team) else away if _team_matches(away, team) else None
        if team_row is None:
            continue
        game_id = str(game.get("gameId") or "")
        accepted_games.append(game_id)
        skaters = [row for row in team_row.get("skaters", []) if isinstance(row, dict)] if isinstance(team_row.get("skaters"), list) else []
        goalies = [row for row in team_row.get("goalies", []) if isinstance(row, dict)] if isinstance(team_row.get("goalies"), list) else []
        team_sog = sum(_num(row.get("sog")) for row in skaters)

        for goalie in goalies:
            toi = _toi_minutes(goalie.get("toi"))
            if toi <= 0 and goalie.get("starter") is not True:
                continue
            player_id = str(goalie.get("playerId") or goalie.get("name") or "")
            player = _name(goalie.get("name"))
            if not player_id or not player:
                continue
            entry = goalie_samples.setdefault(player_id, {"player_id": player_id, "player": player, "rows": []})
            entry["rows"].append(
                {
                    "game_id": game_id,
                    "game_time_utc": when.isoformat(),
                    "starter": goalie.get("starter") is True,
                    "shots_against": _num(goalie.get("shotsAgainst")),
                    "saves": _num(goalie.get("saves")),
                    "goals_against": _num(goalie.get("goalsAgainst")),
                    "save_pct": _num(goalie.get("savePctg")) if goalie.get("savePctg") is not None else None,
                    "toi_minutes": toi,
                    "decision": goalie.get("decision"),
                }
            )

        for skater in skaters:
            toi = _toi_minutes(skater.get("toi"))
            sog = _num(skater.get("sog"))
            if toi <= 0 and sog <= 0:
                continue
            player_id = str(skater.get("playerId") or skater.get("name") or "")
            player = _name(skater.get("name"))
            if not player_id or not player:
                continue
            entry = skater_samples.setdefault(
                player_id,
                {
                    "player_id": player_id,
                    "player": player,
                    "position": skater.get("position"),
                    "rows": [],
                },
            )
            entry["rows"].append(
                {
                    "game_id": game_id,
                    "game_time_utc": when.isoformat(),
                    "sog": sog,
                    "shot_share": sog / team_sog if team_sog > 0 else None,
                    "toi_minutes": toi,
                }
            )

    sample_games = len(set(accepted_games))
    goalies_out: list[dict[str, Any]] = []
    for entry in goalie_samples.values():
        rows = sorted(entry.pop("rows"), key=lambda row: row["game_time_utc"])
        shots_against = [float(row["shots_against"]) for row in rows]
        saves = [float(row["saves"]) for row in rows]
        total_shots = sum(shots_against)
        total_saves = sum(saves)
        starts = sum(1 for row in rows if row["starter"])
        goalies_out.append(
            {
                **entry,
                "appearances": len(rows),
                "starts": starts,
                "historical_start_rate": _round(starts / sample_games, 3) if sample_games else None,
                "average_shots_against": _round(_avg(shots_against), 2),
                "last_three_shots_against": _round(_avg(shots_against[-3:]), 2),
                "average_saves": _round(_avg(saves), 2),
                "weighted_save_pct": _round(total_saves / total_shots, 4) if total_shots > 0 else None,
                "average_goals_against": _round(_avg([float(row["goals_against"]) for row in rows]), 2),
                "average_toi_minutes": _round(_avg([float(row["toi_minutes"]) for row in rows]), 2),
                "last_historical_start": next((row["game_time_utc"] for row in reversed(rows) if row["starter"]), None),
                "goalie_sample": rows,
            }
        )
    goalies_out.sort(key=lambda row: (row.get("starts") or 0, row.get("average_toi_minutes") or 0), reverse=True)

    skaters_out: list[dict[str, Any]] = []
    for entry in skater_samples.values():
        rows = sorted(entry.pop("rows"), key=lambda row: row["game_time_utc"])
        sog = [float(row["sog"]) for row in rows]
        shares = [float(row["shot_share"]) for row in rows if row["shot_share"] is not None]
        skaters_out.append(
            {
                **entry,
                "games": len(rows),
                "average_sog": _round(_avg(sog), 2),
                "last_three_sog": _round(_avg(sog[-3:]), 2),
                "average_shot_share": _round(_avg(shares), 4),
                "average_toi_minutes": _round(_avg([float(row["toi_minutes"]) for row in rows]), 2),
                "shot_sample": rows,
            }
        )
    skaters_out.sort(key=lambda row: (row.get("average_sog") or 0, row.get("average_shot_share") or 0), reverse=True)

    return {
        "team": team,
        "games_used": list(dict.fromkeys(accepted_games)),
        "sample_games": sample_games,
        "goalies": goalies_out,
        "skaters": skaters_out,
        "starting_goalie_confirmation": {
            "status": "UNAVAILABLE_WITHOUT_VERIFIED_PREGAME_CONFIRMATION_SOURCE",
            "confirmed": False,
            "goalie": None,
            "source": None,
            "confirmed_at": None,
        },
    }


def _response_json(session: requests.Session, url: str) -> Any:
    response = session.get(url, headers={"Accept": "application/json"}, timeout=(3, 12))
    response.raise_for_status()
    return response.json()


def _aliases(team: dict[str, Any] | None) -> set[str]:
    if not isinstance(team, dict):
        return set()
    aliases = {_norm(team.get("abbrev"))}
    common = _name(team.get("commonName"))
    place = _name(team.get("placeName"))
    name = _name(team.get("name"))
    if common:
        aliases.add(_norm(common))
    if name:
        aliases.add(_norm(name))
    if place and common:
        aliases.add(_norm(f"{place} {common}"))
    return {alias for alias in aliases if alias}


def _matches_name(team: dict[str, Any] | None, target: str) -> bool:
    wanted = _norm(target)
    return bool(wanted and any(alias == wanted or alias in wanted or wanted in alias for alias in _aliases(team)))


def _find_target_game(schedule: dict[str, Any], event: dict[str, Any]) -> dict[str, Any] | None:
    event_id = str(event.get("id") or event.get("event_id") or "")
    home = str(event.get("home_team") or event.get("home") or "")
    away = str(event.get("away_team") or event.get("away") or "")
    for day in schedule.get("gameWeek", []) if isinstance(schedule, dict) and isinstance(schedule.get("gameWeek"), list) else []:
        games = day.get("games") if isinstance(day, dict) and isinstance(day.get("games"), list) else []
        for game in games:
            if not isinstance(game, dict):
                continue
            if event_id and str(game.get("id") or "") == event_id:
                return game
            if _matches_name(game.get("homeTeam"), home) and _matches_name(game.get("awayTeam"), away):
                return game
    return None


def _normalize_boxscore(raw: dict[str, Any], start_time: str) -> dict[str, Any]:
    player_stats = raw.get("playerByGameStats") if isinstance(raw.get("playerByGameStats"), dict) else {}

    def side(which: str) -> dict[str, Any]:
        team = raw.get(which) if isinstance(raw.get(which), dict) else {}
        stats = player_stats.get(which) if isinstance(player_stats.get(which), dict) else {}
        forwards = stats.get("forwards") if isinstance(stats.get("forwards"), list) else []
        defense = stats.get("defense") if isinstance(stats.get("defense"), list) else []
        goalies = stats.get("goalies") if isinstance(stats.get("goalies"), list) else []
        return {
            "abbrev": team.get("abbrev"),
            "teamName": _name(team.get("commonName")) or _name(team.get("name")) or team.get("abbrev"),
            "skaters": [row for row in [*forwards, *defense] if isinstance(row, dict)],
            "goalies": [row for row in goalies if isinstance(row, dict)],
        }

    return {
        "gameId": str(raw.get("id") or ""),
        "gameTimeUTC": start_time,
        "gameStatusText": "FINAL",
        "homeTeam": side("homeTeam"),
        "awayTeam": side("awayTeam"),
    }


def fetch_nhl_role_context(
    event: dict[str, Any],
    *,
    session: requests.Session | None = None,
    lookback_games: int = 5,
) -> dict[str, Any]:
    """Fetch point-in-time NHL goalie workload and skater-shot context.

    Historical official starter flags are not treated as confirmation of the
    upcoming starter. A separate verified pregame confirmation source is still
    required before `starting_goalie_confirmation.confirmed` can become true.
    """

    target = _utc(event.get("commence_time") or event.get("event_time"))
    now = datetime.now(timezone.utc)
    if target is None or target <= now:
        return {
            "status": "NOT_PREGAME",
            "sport": "NHL",
            "event_id": str(event.get("id") or event.get("event_id") or ""),
            "model_influence": False,
        }

    client = session or requests.Session()
    schedule = _response_json(client, f"https://api-web.nhle.com/v1/schedule/{target.date().isoformat()}")
    target_game = _find_target_game(schedule, event)
    if target_game is None:
        return {
            "status": "TARGET_EVENT_NOT_MATCHED",
            "sport": "NHL",
            "event_id": str(event.get("id") or event.get("event_id") or ""),
            "model_influence": False,
        }

    home_team = target_game.get("homeTeam") if isinstance(target_game.get("homeTeam"), dict) else {}
    away_team = target_game.get("awayTeam") if isinstance(target_game.get("awayTeam"), dict) else {}
    home_abbrev = str(home_team.get("abbrev") or "")
    away_abbrev = str(away_team.get("abbrev") or "")
    season = target_game.get("season")
    game_type = target_game.get("gameType")
    if not home_abbrev or not away_abbrev or season is None:
        raise ValueError("NHL target event is missing team abbreviations or season")

    schedules = []
    for abbrev in (home_abbrev, away_abbrev):
        schedules.append(_response_json(client, f"https://api-web.nhle.com/v1/club-schedule-season/{abbrev}/{season}"))

    def recent(schedule_payload: dict[str, Any], abbrev: str) -> list[tuple[datetime, str]]:
        rows: list[tuple[datetime, str]] = []
        games = schedule_payload.get("games") if isinstance(schedule_payload.get("games"), list) else []
        for row in games:
            if not isinstance(row, dict):
                continue
            when = _utc(row.get("startTimeUTC"))
            state = str(row.get("gameState") or "").upper()
            if when is None or when >= target or state not in {"FINAL", "OFF"}:
                continue
            if game_type is not None and row.get("gameType") != game_type:
                continue
            row_home = row.get("homeTeam") if isinstance(row.get("homeTeam"), dict) else {}
            row_away = row.get("awayTeam") if isinstance(row.get("awayTeam"), dict) else {}
            if str(row_home.get("abbrev") or row_away.get("abbrev") or "") == "":
                continue
            if abbrev not in {str(row_home.get("abbrev") or ""), str(row_away.get("abbrev") or "")}:
                continue
            game_id = str(row.get("id") or "")
            if game_id:
                rows.append((when, game_id))
        rows.sort(reverse=True)
        return rows[:lookback_games]

    history = list(dict.fromkeys(recent(schedules[0], home_abbrev) + recent(schedules[1], away_abbrev)))
    history.sort(reverse=True)
    start_by_id = {game_id: when for when, game_id in history}
    game_ids = list(start_by_id)
    boxes: list[dict[str, Any]] = []
    failures = 0
    for game_id in game_ids:
        try:
            raw = _response_json(client, f"https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore")
            if not isinstance(raw, dict):
                raise ValueError("NHL boxscore was not an object")
            boxes.append(_normalize_boxscore(raw, start_by_id[game_id].isoformat()))
        except Exception:
            failures += 1

    home = summarize_team_role(home_abbrev, boxes, target.isoformat())
    away = summarize_team_role(away_abbrev, boxes, target.isoformat())
    if home["sample_games"] and away["sample_games"]:
        status = "PARTIAL_VERIFIED_CONTEXT" if failures else "VERIFIED_CONTEXT"
    else:
        status = "INSUFFICIENT_COMPLETED_GAME_CONTEXT"
    return {
        "status": status,
        "sport": "NHL",
        "event_id": str(event.get("id") or event.get("event_id") or target_game.get("id") or ""),
        "target_event_time": target.isoformat(),
        "season": season,
        "game_type": game_type,
        "source": "nhl_web_api_schedule_and_gamecenter_boxscore",
        "source_health": {
            "boxscores_requested": len(game_ids),
            "boxscores_loaded": len(boxes),
            "boxscores_failed": failures,
        },
        "point_in_time_rule": "only FINAL/OFF same-game-type games with startTimeUTC < target_event_time",
        "goalie_method": "official historical starter flag plus saves/shotsAgainst/TOI workload",
        "skater_method": "official settled-game SOG and TOI with team shot share",
        "starting_goalie_confirmation_policy": "historical starts never imply upcoming confirmation",
        "model_influence": False,
        "promotion_policy": "context_only_until_promoted_artifact_declares_compatible_nhl_role_features",
        "home": home,
        "away": away,
        "observed_at": now.isoformat(),
    }
