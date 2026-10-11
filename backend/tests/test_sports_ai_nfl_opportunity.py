from __future__ import annotations

from sports_ai.sports.nfl.opportunity import summarize_team_opportunity


def game(game_id: str, when: str, *, status: str = "Final") -> dict:
    return {
        "gameId": game_id,
        "gameTimeUTC": when,
        "gameStatusText": status,
        "homeTeam": {
            "teamName": "Detroit Lions",
            "players": [
                {
                    "personId": "rb",
                    "name": "Runner",
                    "carries": 20,
                    "rushingYards": 100,
                    "targets": 4,
                    "receptions": 3,
                    "receivingYards": 25,
                },
                {
                    "personId": "wr",
                    "name": "Receiver",
                    "carries": 1,
                    "rushingYards": 5,
                    "targets": 10,
                    "receptions": 7,
                    "receivingYards": 90,
                },
            ],
        },
        "awayTeam": {"teamName": "Arizona Cardinals", "players": []},
    }


def test_opportunity_summary_is_point_in_time_and_same_boxscore_math() -> None:
    result = summarize_team_opportunity(
        "Detroit Lions",
        [
            game("g1", "2026-09-20T20:00:00Z"),
            game("g2", "2026-09-27T20:00:00Z"),
            game("future", "2026-10-20T20:00:00Z"),
            game("not-final", "2026-10-01T20:00:00Z", status="Scheduled"),
        ],
        "2026-10-10T20:00:00Z",
    )
    assert result["sample_games"] == 2
    assert result["games_used"] == ["g1", "g2"]
    runner = next(row for row in result["players"] if row["player"] == "Runner")
    assert runner["average_carries"] == 20.0
    assert runner["average_targets"] == 4.0
    assert runner["average_carry_share"] > 0.9
    assert runner["snap_share"] is None
    assert runner["snap_share_status"] == "UNAVAILABLE_FROM_ESPN_BOXSCORE"
    assert result["snap_share_available"] is False


def test_opportunity_summary_target_share_uses_team_targets() -> None:
    result = summarize_team_opportunity(
        "Detroit Lions",
        [game("g1", "2026-09-20T20:00:00Z")],
        "2026-10-10T20:00:00Z",
    )
    receiver = next(row for row in result["players"] if row["player"] == "Receiver")
    assert receiver["average_target_share"] == round(10 / 14, 4)
    assert receiver["average_opportunities"] == 11.0
