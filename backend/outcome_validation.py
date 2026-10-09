from __future__ import annotations

from datetime import date as date_cls
from typing import Any

import requests

ESPN = {
    "NFL": ("football", "nfl"),
    "NBA": ("basketball", "nba"),
}


def _json(url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.get(url, params=params, timeout=12, headers={"Accept": "application/json"})
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("outcome provider returned non-object JSON")
    return payload


def _espn_results(sport: str, day: date_cls) -> list[dict[str, Any]]:
    a, b = ESPN[sport]
    raw = _json(
        f"https://site.api.espn.com/apis/site/v2/sports/{a}/{b}/scoreboard",
        params={"dates": day.strftime("%Y%m%d"), "limit": 1000},
    )
    out = []
    for event in raw.get("events") or []:
        comp = (event.get("competitions") or [{}])[0]
        teams = comp.get("competitors") or []
        home = next((row for row in teams if row.get("homeAway") == "home"), None)
        away = next((row for row in teams if row.get("homeAway") == "away"), None)
        status = (event.get("status") or {}).get("type") or {}
        if not home or not away:
            continue
        out.append({
            "sport": sport,
            "event_id": str(event.get("id") or ""),
            "home": (home.get("team") or {}).get("displayName"),
            "away": (away.get("team") or {}).get("displayName"),
            "home_score": home.get("score"),
            "away_score": away.get("score"),
            "completed": status.get("completed") is True or str(status.get("state") or "").lower() == "post",
            "source": "ESPN",
        })
    return out


def _mlb_results(day: date_cls) -> list[dict[str, Any]]:
    raw = _json(
        "https://statsapi.mlb.com/api/v1/schedule",
        params={"sportId": 1, "date": day.isoformat()},
    )
    out = []
    for date_row in raw.get("dates") or []:
        for game in date_row.get("games") or []:
            teams = game.get("teams") or {}
            home, away = teams.get("home") or {}, teams.get("away") or {}
            out.append({
                "sport": "MLB", "event_id": str(game.get("gamePk") or ""),
                "home": (home.get("team") or {}).get("name"), "away": (away.get("team") or {}).get("name"),
                "home_score": home.get("score"), "away_score": away.get("score"),
                "completed": str((game.get("status") or {}).get("abstractGameState") or "").lower() == "final",
                "source": "MLB StatsAPI",
            })
    return out


def _nhl_results(day: date_cls) -> list[dict[str, Any]]:
    raw = _json(f"https://api-web.nhle.com/v1/schedule/{day.isoformat()}")
    out = []
    for week in raw.get("gameWeek") or []:
        if week.get("date") != day.isoformat():
            continue
        for game in week.get("games") or []:
            home, away = game.get("homeTeam") or {}, game.get("awayTeam") or {}

            def name(team: dict[str, Any]) -> str | None:
                value = team.get("name") or team.get("commonName") or team.get("placeName")
                if isinstance(value, dict):
                    return value.get("default") or next(iter(value.values()), None)
                return value or team.get("abbrev")

            out.append({
                "sport": "NHL", "event_id": str(game.get("id") or ""),
                "home": name(home), "away": name(away),
                "home_score": home.get("score"), "away_score": away.get("score"),
                "completed": str(game.get("gameState") or "").upper() in {"FINAL", "OFF"},
                "source": "NHL Web API",
            })
    return out


def results_for_date(sport: str, day: date_cls) -> list[dict[str, Any]]:
    sport = sport.upper()
    if sport == "MLB":
        return _mlb_results(day)
    if sport == "NHL":
        return _nhl_results(day)
    if sport in ESPN:
        return _espn_results(sport, day)
    raise ValueError(f"unsupported sport: {sport}")
