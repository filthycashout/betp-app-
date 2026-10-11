from __future__ import annotations

from sports_ai.sports.mlb.role import extract_target_state, summarize_team_role


def game(game_pk: str, when: str, *, status: str = "Final") -> dict:
    return {
        "gamePk": game_pk,
        "gameDate": when,
        "gameStatusText": status,
        "homeTeam": {
            "id": 119,
            "name": "Los Angeles Dodgers",
            "battingOrder": ["1", "2"],
            "hitters": [
                {
                    "personId": "1",
                    "name": "Leadoff",
                    "lineupSlot": 1,
                    "plateAppearances": 5,
                    "atBats": 4,
                    "hits": 2,
                    "baseOnBalls": 1,
                    "strikeOuts": 1,
                    "homeRuns": 0,
                    "totalBases": 3,
                    "rbi": 1,
                    "runs": 1,
                },
                {
                    "personId": "2",
                    "name": "Second",
                    "lineupSlot": 2,
                    "plateAppearances": 4,
                    "atBats": 4,
                    "hits": 1,
                    "baseOnBalls": 0,
                    "strikeOuts": 2,
                    "homeRuns": 1,
                    "totalBases": 4,
                    "rbi": 2,
                    "runs": 1,
                },
            ],
        },
        "awayTeam": {"id": 137, "name": "San Francisco Giants", "battingOrder": [], "hitters": []},
    }


def test_mlb_role_context_is_point_in_time_and_tracks_plate_appearances() -> None:
    result = summarize_team_role(
        119,
        [
            game("g1", "2026-10-01T00:00:00Z"),
            game("g2", "2026-10-05T00:00:00Z"),
            game("future", "2026-10-20T00:00:00Z"),
            game("not-final", "2026-10-06T00:00:00Z", status="Preview"),
        ],
        "2026-10-10T00:00:00Z",
    )
    assert result["sample_games"] == 2
    leadoff = next(row for row in result["hitters"] if row["player"] == "Leadoff")
    assert leadoff["average_plate_appearances"] == 5.0
    assert leadoff["average_lineup_slot"] == 1.0
    assert leadoff["start_rate"] == 1.0
    assert leadoff["average_hits"] == 2.0


def test_extract_target_state_separates_posted_lineup_from_probable_pitcher() -> None:
    players = {f"ID{i}": {"fullName": f"Batter {i}"} for i in range(1, 10)}
    feed = {
        "gameData": {
            "players": players,
            "probablePitchers": {
                "home": {"id": 99, "fullName": "Home Pitcher"},
                "away": {"id": 88, "fullName": "Away Pitcher"},
            },
        },
        "liveData": {
            "boxscore": {
                "teams": {
                    "home": {"battingOrder": list(range(1, 10))},
                    "away": {"battingOrder": []},
                }
            }
        },
    }
    state = extract_target_state(feed)
    assert state["home_lineup"]["confirmed"] is True
    assert len(state["home_lineup"]["batting_order"]) == 9
    assert state["away_lineup"]["status"] == "UNAVAILABLE_NOT_POSTED"
    assert state["home_probable_pitcher"]["status"] == "PROBABLE"
    assert state["home_probable_pitcher"]["player"] == "Home Pitcher"
