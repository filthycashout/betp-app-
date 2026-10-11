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


def _round(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


def _avg(values: list[float]) -> float | None:
    return mean(values) if values else None


def _team_matches(team: dict[str, Any] | None, target: str) -> bool:
    if not isinstance(team, dict):
        return False
    wanted = _norm(target)
    candidate = _norm(team.get("teamName") or team.get("displayName") or team.get("name"))
    return bool(wanted and candidate and (wanted == candidate or wanted in candidate or candidate in wanted))


def summarize_team_opportunity(team_name: str, games: list[dict[str, Any]], target_event_time: str) -> dict[str, Any]:
    """Summarize NFL carries/targets from settled games strictly before kickoff.

    ESPN box scores expose rushing attempts and receiving targets but not snap
    counts. Snap share therefore remains explicitly unavailable rather than
    being inferred from touches or target share.
    """

    target = _utc(target_event_time)
    if target is None:
        raise ValueError("target_event_time must be a valid timestamp")

    samples: dict[str, dict[str, Any]] = {}
    accepted_games: list[str] = []
    chronological: list[tuple[datetime, dict[str, Any]]] = []
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
        players = team.get("players") if isinstance(team.get("players"), list) else []
        typed_players = [row for row in players if isinstance(row, dict)]
        team_carries = sum(_num(row.get("carries")) for row in typed_players)
        team_targets = sum(_num(row.get("targets")) for row in typed_players)
        team_opportunities = team_carries + team_targets
        game_id = str(game.get("gameId") or "")
        accepted_games.append(game_id)

        for player in typed_players:
            carries = _num(player.get("carries"))
            targets = _num(player.get("targets"))
            if carries <= 0 and targets <= 0:
                continue
            player_id = str(player.get("personId") or player.get("name") or "")
            name = str(player.get("name") or "").strip()
            if not player_id or not name:
                continue
            entry = samples.setdefault(player_id, {"player_id": player_id, "player": name, "rows": []})
            entry["rows"].append(
                {
                    "game_id": game_id,
                    "game_time_utc": when.isoformat(),
                    "carries": carries,
                    "targets": targets,
                    "receptions": _num(player.get("receptions")),
                    "rushing_yards": _num(player.get("rushingYards")),
                    "receiving_yards": _num(player.get("receivingYards")),
                    "carry_share": carries / team_carries if team_carries > 0 else None,
                    "target_share": targets / team_targets if team_targets > 0 else None,
                    "opportunity_share": (carries + targets) / team_opportunities if team_opportunities > 0 else None,
                }
            )

    output: list[dict[str, Any]] = []
    for entry in samples.values():
        rows = sorted(entry.pop("rows"), key=lambda row: row["game_time_utc"])
        carries = [float(row["carries"]) for row in rows]
        targets = [float(row["targets"]) for row in rows]
        opportunities = [float(row["carries"] + row["targets"]) for row in rows]
        carry_shares = [float(row["carry_share"]) for row in rows if row["carry_share"] is not None]
        target_shares = [float(row["target_share"]) for row in rows if row["target_share"] is not None]
        opportunity_shares = [float(row["opportunity_share"]) for row in rows if row["opportunity_share"] is not None]
        output.append(
            {
                **entry,
                "games": len(rows),
                "average_carries": _round(_avg(carries), 2),
                "average_targets": _round(_avg(targets), 2),
                "average_opportunities": _round(_avg(opportunities), 2),
                "last_three_carries": _round(_avg(carries[-3:]), 2),
                "last_three_targets": _round(_avg(targets[-3:]), 2),
                "average_carry_share": _round(_avg(carry_shares), 4),
                "average_target_share": _round(_avg(target_shares), 4),
                "average_opportunity_share": _round(_avg(opportunity_shares), 4),
                "average_receptions": _round(_avg([float(row["receptions"]) for row in rows]), 2),
                "average_rushing_yards": _round(_avg([float(row["rushing_yards"]) for row in rows]), 2),
                "average_receiving_yards": _round(_avg([float(row["receiving_yards"]) for row in rows]), 2),
                "snap_share": None,
                "snap_share_status": "UNAVAILABLE_FROM_ESPN_BOXSCORE",
                "opportunity_sample": rows,
            }
        )
    output.sort(key=lambda row: row.get("average_opportunities") or 0.0, reverse=True)
    return {
        "team": team_name,
        "games_used": list(dict.fromkeys(accepted_games)),
        "sample_games": len(set(accepted_games)),
        "players": output,
        "snap_share_available": False,
    }


def _response_json(session: requests.Session, url: str, *, params: dict[str, Any] | None = None) -> Any:
    response = session.get(url, params=params, headers={"Accept": "application/json"}, timeout=(3, 12))
    response.raise_for_status()
    return response.json()


def _event_teams(event: dict[str, Any]) -> list[str]:
    comps = event.get("competitions") if isinstance(event.get("competitions"), list) else []
    competitors = comps[0].get("competitors") if comps and isinstance(comps[0], dict) and isinstance(comps[0].get("competitors"), list) else []
    names: list[str] = []
    for row in competitors:
        team = row.get("team") if isinstance(row, dict) and isinstance(row.get("team"), dict) else {}
        name = str(team.get("displayName") or "").strip()
        if name:
            names.append(name)
    return names


def _has_team(event: dict[str, Any], team: str) -> bool:
    wanted = _norm(team)
    return any(
        candidate and wanted and (candidate == wanted or candidate in wanted or wanted in candidate)
        for candidate in (_norm(name) for name in _event_teams(event))
    )


def _same_target_event(row: dict[str, Any], event: dict[str, Any]) -> bool:
    if not _has_team(row, str(event.get("home_team") or event.get("home") or "")):
        return False
    if not _has_team(row, str(event.get("away_team") or event.get("away") or "")):
        return False
    left = _utc(row.get("date"))
    right = _utc(event.get("commence_time") or event.get("event_time"))
    return bool(left and right and abs((left - right).total_seconds()) <= 30 * 60)


def _block_value(block: dict[str, Any], athlete_row: dict[str, Any], key: str) -> Any:
    keys = [str(value) for value in block.get("keys", [])] if isinstance(block.get("keys"), list) else []
    stats = athlete_row.get("stats") if isinstance(athlete_row.get("stats"), list) else []
    try:
        return stats[keys.index(key)]
    except (ValueError, IndexError):
        return None


def _normalize_summary_team(group: dict[str, Any]) -> dict[str, Any]:
    by_player: dict[str, dict[str, Any]] = {}
    blocks = group.get("statistics") if isinstance(group.get("statistics"), list) else []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_name = str(block.get("name") or block.get("type") or "").lower()
        if block_name not in {"rushing", "receiving"}:
            continue
        athletes = block.get("athletes") if isinstance(block.get("athletes"), list) else []
        for row in athletes:
            if not isinstance(row, dict):
                continue
            athlete = row.get("athlete") if isinstance(row.get("athlete"), dict) else {}
            player_id = str(athlete.get("id") or athlete.get("displayName") or "")
            name = str(athlete.get("displayName") or "").strip()
            if not player_id or not name:
                continue
            entry = by_player.setdefault(
                player_id,
                {
                    "personId": player_id,
                    "name": name,
                    "carries": 0.0,
                    "rushingYards": 0.0,
                    "targets": 0.0,
                    "receptions": 0.0,
                    "receivingYards": 0.0,
                },
            )
            if block_name == "rushing":
                entry["carries"] = _num(_block_value(block, row, "rushingAttempts"))
                entry["rushingYards"] = _num(_block_value(block, row, "rushingYards"))
            else:
                entry["targets"] = _num(_block_value(block, row, "receivingTargets"))
                entry["receptions"] = _num(_block_value(block, row, "receptions"))
                entry["receivingYards"] = _num(_block_value(block, row, "receivingYards"))
    team = group.get("team") if isinstance(group.get("team"), dict) else {}
    return {
        "teamName": str(team.get("displayName") or team.get("name") or ""),
        "players": list(by_player.values()),
    }


def _month_key(value: datetime) -> str:
    return f"{value.year:04d}{value.month:02d}"


def fetch_nfl_opportunity_context(
    event: dict[str, Any],
    *,
    session: requests.Session | None = None,
    lookback_games: int = 5,
) -> dict[str, Any]:
    """Fetch settled NFL carry/target context without letting it affect predictions."""

    target = _utc(event.get("commence_time") or event.get("event_time"))
    now = datetime.now(timezone.utc)
    if target is None or target <= now:
        return {
            "status": "NOT_PREGAME",
            "sport": "NFL",
            "event_id": str(event.get("id") or event.get("event_id") or ""),
            "model_influence": False,
        }

    client = session or requests.Session()
    previous_month = target.month - 1 or 12
    previous_year = target.year - 1 if target.month == 1 else target.year
    month_values = [datetime(previous_year, previous_month, 1, tzinfo=timezone.utc), datetime(target.year, target.month, 1, tzinfo=timezone.utc)]
    months = list(dict.fromkeys(_month_key(value) for value in month_values))
    by_id: dict[str, dict[str, Any]] = {}
    for month in months:
        payload = _response_json(
            client,
            "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
            params={"dates": month, "limit": 1000},
        )
        events = payload.get("events") if isinstance(payload, dict) and isinstance(payload.get("events"), list) else []
        for row in events:
            if isinstance(row, dict) and row.get("id"):
                by_id[str(row["id"])] = row

    events = list(by_id.values())
    target_event = next((row for row in events if _same_target_event(row, event)), None)
    target_season_type = None
    if isinstance(target_event, dict) and isinstance(target_event.get("season"), dict):
        target_season_type = target_event["season"].get("type")

    def recent_ids(team: str) -> list[str]:
        candidates: list[tuple[datetime, str]] = []
        for row in events:
            when = _utc(row.get("date"))
            status = row.get("status") if isinstance(row.get("status"), dict) else {}
            status_type = status.get("type") if isinstance(status.get("type"), dict) else {}
            season_type = row.get("season", {}).get("type") if isinstance(row.get("season"), dict) else None
            if when is None or when >= target:
                continue
            if status_type.get("completed") is not True and str(status_type.get("state") or "").lower() != "post":
                continue
            if target_season_type is not None and season_type != target_season_type:
                continue
            if _has_team(row, team):
                candidates.append((when, str(row.get("id") or "")))
        candidates.sort(reverse=True)
        return [game_id for _, game_id in candidates[:lookback_games] if game_id]

    game_ids = list(
        dict.fromkeys(
            recent_ids(str(event.get("home_team") or event.get("home") or ""))
            + recent_ids(str(event.get("away_team") or event.get("away") or ""))
        )
    )
    boxes: list[dict[str, Any]] = []
    failures = 0
    for game_id in game_ids:
        try:
            payload = _response_json(
                client,
                "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary",
                params={"event": game_id},
            )
            box = payload.get("boxscore") if isinstance(payload, dict) and isinstance(payload.get("boxscore"), dict) else {}
            groups = box.get("players") if isinstance(box.get("players"), list) else []
            if len(groups) < 2 or not all(isinstance(group, dict) for group in groups[:2]):
                raise ValueError("ESPN NFL summary did not contain player boxscore groups")
            source_event = by_id[game_id]
            boxes.append(
                {
                    "gameId": game_id,
                    "gameTimeUTC": source_event.get("date"),
                    "gameStatusText": "Final",
                    "homeTeam": _normalize_summary_team(groups[0]),
                    "awayTeam": _normalize_summary_team(groups[1]),
                }
            )
        except Exception:
            failures += 1

    home_name = str(event.get("home_team") or event.get("home") or "")
    away_name = str(event.get("away_team") or event.get("away") or "")
    home = summarize_team_opportunity(home_name, boxes, target.isoformat())
    away = summarize_team_opportunity(away_name, boxes, target.isoformat())
    if home["sample_games"] and away["sample_games"]:
        status = "PARTIAL_VERIFIED_CONTEXT" if failures else "VERIFIED_CONTEXT"
    else:
        status = "INSUFFICIENT_COMPLETED_GAME_CONTEXT"
    return {
        "status": status,
        "sport": "NFL",
        "event_id": str(event.get("id") or event.get("event_id") or ""),
        "target_event_time": target.isoformat(),
        "source": "espn_site_api_scoreboard_summary",
        "source_health": {
            "scoreboard_months": months,
            "boxscores_requested": len(game_ids),
            "boxscores_loaded": len(boxes),
            "boxscores_failed": failures,
        },
        "season_type": target_season_type,
        "point_in_time_rule": "only final same-season games with event_time < target_event_time",
        "opportunity_method": "settled boxscore rushing attempts and receiving targets",
        "snap_share_status": "UNAVAILABLE_FROM_ESPN_BOXSCORE",
        "model_influence": False,
        "promotion_policy": "context_only_until_promoted_artifact_declares_compatible_opportunity_features",
        "home": home,
        "away": away,
        "observed_at": now.isoformat(),
    }
