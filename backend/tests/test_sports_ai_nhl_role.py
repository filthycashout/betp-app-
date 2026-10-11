from __future__ import annotations

from sports_ai.sports.nhl.role import summarize_team_role


def game(game_id: str, when: str, *, status: str = "FINAL") -> dict:
    return {
        "gameId": game_id,
        "gameTimeUTC": when,
        "gameStatusText": status,
        "homeTeam": {
            "abbrev": "BOS",
            "teamName": "Bruins",
            "goalies": [
                {
                    "playerId": 1,
                    "name": {"default": "Goalie One"},
                    "starter": True,
                    "shotsAgainst": 30,
                    "saves": 28,
                    "goalsAgainst": 2,
                    "savePctg": 0.9333,
                    "toi": "60:00",
                    "decision": "W",
                }
            ],
            "skaters": [
                {"playerId": 10, "name": {"default": "Shooter"}, "position": "C", "sog": 5, "toi": "20:00"},
                {"playerId": 11, "name": {"default": "Wing"}, "position": "L", "sog": 3, "toi": "18:00"},
            ],
        },
        "awayTeam": {"abbrev": "NYR", "teamName": "Rangers", "goalies": [], "skaters": []},
    }


def test_nhl_role_context_is_point_in_time_and_tracks_goalie_workload() -> None:
    result = summarize_team_role(
        "BOS",
        [
            game("g1", "2026-10-01T00:00:00Z"),
            game("g2", "2026-10-05T00:00:00Z"),
            game("future", "2026-10-20T00:00:00Z"),
            game("not-final", "2026-10-06T00:00:00Z", status="FUT"),
        ],
        "2026-10-10T00:00:00Z",
    )
    assert result["sample_games"] == 2
    assert result["games_used"] == ["g1", "g2"]
    goalie = result["goalies"][0]
    assert goalie["starts"] == 2
    assert goalie["historical_start_rate"] == 1.0
    assert goalie["average_shots_against"] == 30.0
    assert goalie["weighted_save_pct"] == round(56 / 60, 4)
    assert result["starting_goalie_confirmation"]["confirmed"] is False
    assert result["starting_goalie_confirmation"]["goalie"] is None


def test_nhl_skater_shot_role_uses_team_sog_share() -> None:
    result = summarize_team_role(
        "Boston Bruins",
        [game("g1", "2026-10-01T00:00:00Z")],
        "2026-10-10T00:00:00Z",
    )
    shooter = next(row for row in result["skaters"] if row["player"] == "Shooter")
    assert shooter["average_sog"] == 5.0
    assert shooter["average_shot_share"] == 0.625
    assert shooter["average_toi_minutes"] == 20.0


def test_historical_starter_never_becomes_current_confirmation() -> None:
    result = summarize_team_role(
        "BOS",
        [game("g1", "2026-10-01T00:00:00Z")],
        "2026-10-10T00:00:00Z",
    )
    confirmation = result["starting_goalie_confirmation"]
    assert confirmation["status"] == "UNAVAILABLE_WITHOUT_VERIFIED_PREGAME_CONFIRMATION_SOURCE"
    assert confirmation["confirmed"] is False
