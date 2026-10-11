from __future__ import annotations

from sports_ai.sports.nba.role import summarize_team_role


def player(player_id: int, name: str, minutes: str, fga: int, fta: int, turnovers: int, *, starter: str = "1") -> dict:
    return {
        "personId": player_id,
        "name": name,
        "position": "G",
        "starter": starter,
        "played": "1",
        "statistics": {
            "minutes": minutes,
            "fieldGoalsAttempted": fga,
            "freeThrowsAttempted": fta,
            "turnovers": turnovers,
            "points": 20,
            "reboundsTotal": 5,
            "assists": 7,
        },
    }


def game(game_id: str, when: str, minutes: str, *, status: str = "Final") -> dict:
    return {
        "gameId": game_id,
        "gameTimeUTC": when,
        "gameStatusText": status,
        "homeTeam": {
            "teamCity": "Los Angeles",
            "teamName": "Lakers",
            "players": [
                player(1, "Guard One", minutes, 15, 5, 3),
                player(2, "Guard Two", "PT20M00.00S", 8, 2, 1, starter="0"),
            ],
        },
        "awayTeam": {"teamCity": "Phoenix", "teamName": "Suns", "players": []},
    }


def test_role_summary_is_point_in_time_and_rolling() -> None:
    result = summarize_team_role(
        "Los Angeles Lakers",
        [
            game("g1", "2026-10-01T00:00:00Z", "PT30M00.00S"),
            game("g2", "2026-10-05T00:00:00Z", "PT33M00.00S"),
            game("future", "2026-10-20T00:00:00Z", "PT48M00.00S"),
            game("not-final", "2026-10-06T00:00:00Z", "PT48M00.00S", status="Scheduled"),
        ],
        "2026-10-10T00:00:00Z",
    )
    assert result["sample_games"] == 2
    assert result["games_used"] == ["g1", "g2"]
    guard = next(row for row in result["players"] if row["player"] == "Guard One")
    assert guard["games"] == 2
    assert guard["average_minutes"] == 31.5
    assert guard["last_game_minutes"] == 33.0
    assert guard["average_usage_rate"] is not None
    assert guard["average_usage_rate"] > 0


def test_role_summary_matches_short_team_name_to_full_team() -> None:
    result = summarize_team_role(
        "Los Angeles Lakers",
        [game("g1", "2026-10-01T00:00:00Z", "PT30M00.00S")],
        "2026-10-10T00:00:00Z",
    )
    assert len(result["players"]) == 2


def test_role_summary_accepts_espn_plain_minute_strings() -> None:
    fixture = game("g1", "2026-10-01T00:00:00Z", "PT30M00.00S")
    fixture["homeTeam"]["players"][0]["statistics"]["minutes"] = "27"
    result = summarize_team_role("Los Angeles Lakers", [fixture], "2026-10-10T00:00:00Z")
    guard = next(row for row in result["players"] if row["player"] == "Guard One")
    assert guard["average_minutes"] == 27.0
