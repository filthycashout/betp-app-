from __future__ import annotations

from sports_ai.sports.mlb.statcast import summarize_batter_statcast, summarize_pitcher_statcast


def row(
    game_date: str,
    *,
    game_pk: str = "1",
    pitch_type: str = "FF",
    release_speed: str = "95.0",
    xwoba: str = "0.400",
    launch_speed: str = "100.0",
    launch_angle: str = "20.0",
    launch_speed_angle: str = "6",
    events: str = "single",
) -> dict[str, str]:
    return {
        "game_date": game_date,
        "game_pk": game_pk,
        "pitch_type": pitch_type,
        "release_speed": release_speed,
        "estimated_woba_using_speedangle": xwoba,
        "launch_speed": launch_speed,
        "launch_angle": launch_angle,
        "launch_speed_angle": launch_speed_angle,
        "events": events,
    }


def test_batter_statcast_excludes_target_date_and_future_rows() -> None:
    result = summarize_batter_statcast(
        [
            row("2026-10-01", xwoba="0.300"),
            row("2026-10-09", game_pk="2", xwoba="0.500"),
            row("2026-10-10", game_pk="3", xwoba="0.900"),
            row("2026-10-11", game_pk="4", xwoba="0.999"),
        ],
        "2026-10-10T23:00:00Z",
    )
    assert result["games"] == 2
    assert result["xwoba_on_contact"] == 0.4
    assert result["barrel_rate"] == 1.0


def test_batter_statcast_uses_only_available_batted_ball_values() -> None:
    result = summarize_batter_statcast(
        [
            row("2026-10-01", xwoba="", launch_speed="", launch_angle="", launch_speed_angle=""),
            row("2026-10-02", xwoba="0.250", launch_speed="90", launch_angle="10", launch_speed_angle="4"),
        ],
        "2026-10-10T23:00:00Z",
    )
    assert result["pitch_rows"] == 2
    assert result["batted_ball_events"] == 1
    assert result["xwoba_on_contact"] == 0.25
    assert result["barrel_rate"] == 0.0


def test_pitcher_statcast_builds_pitch_mix_and_velocity() -> None:
    result = summarize_pitcher_statcast(
        [
            row("2026-10-01", pitch_type="FF", release_speed="96", xwoba="0.300"),
            row("2026-10-01", pitch_type="FF", release_speed="94", xwoba=""),
            row("2026-10-02", game_pk="2", pitch_type="SL", release_speed="86", xwoba="0.500"),
            row("2026-10-10", game_pk="3", pitch_type="CH", release_speed="88", xwoba="0.900"),
        ],
        "2026-10-10T23:00:00Z",
    )
    assert result["classified_pitches"] == 3
    assert result["xwoba_allowed_on_contact"] == 0.4
    assert result["pitch_mix"][0] == {
        "pitch_type": "FF",
        "pitches": 2,
        "share": round(2 / 3, 4),
        "average_velocity": 95.0,
    }
    assert result["pitch_mix"][1]["pitch_type"] == "SL"


def test_statcast_target_day_is_conservatively_excluded() -> None:
    result = summarize_pitcher_statcast(
        [row("2026-10-10", pitch_type="FF")],
        "2026-10-10T23:59:00Z",
    )
    assert result["pitch_rows"] == 0
    assert result["pitch_mix"] == []
