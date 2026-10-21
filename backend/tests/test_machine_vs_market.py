from datetime import datetime, timedelta, timezone

import pytest

from sports_ai.machine_vs_market import (
    MachinePrediction,
    MarketObservation,
    SettledOutcome,
    evaluate,
)


T = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)


def prediction(**overrides):
    args = dict(
        sport="NBA", event_id="game-1", target="home_win",
        probability=0.7, predicted_at=T, feature_cutoff_at=T - timedelta(minutes=5),
        event_starts_at=T + timedelta(hours=2), model_version="test-v1",
    )
    args.update(overrides)
    return MachinePrediction(**args)


def outcome(**overrides):
    args = dict(event_id="game-1", target="home_win", actual=1,
                settled_at=T + timedelta(hours=5))
    args.update(overrides)
    return SettledOutcome(**args)


def market(**overrides):
    args = dict(event_id="game-1", target="home_win", probability=0.6,
                observed_at=T + timedelta(minutes=10), source="test-market")
    args.update(overrides)
    return MarketObservation(**args)


def test_independent_machine_beats_market_in_example():
    result = evaluate(prediction(), outcome(), market())
    assert result["machine_brier"] == pytest.approx(0.09)
    assert result["market_brier"] == pytest.approx(0.16)
    assert result["machine_minus_market_brier"] == pytest.approx(-0.07)


def test_evaluation_without_market_is_allowed():
    result = evaluate(prediction(), outcome())
    assert result["market_brier"] is None


def test_market_features_are_rejected():
    with pytest.raises(ValueError, match="market-derived"):
        prediction(market_features_used=True)


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf")])
def test_invalid_machine_probabilities_rejected(value):
    with pytest.raises(ValueError):
        prediction(probability=value)


def test_future_features_rejected():
    with pytest.raises(ValueError):
        prediction(feature_cutoff_at=T + timedelta(seconds=1))


def test_predictions_after_tipoff_rejected():
    with pytest.raises(ValueError):
        prediction(predicted_at=T + timedelta(hours=2))


def test_market_observation_before_freeze_rejected():
    with pytest.raises(ValueError, match="after prediction freeze"):
        evaluate(prediction(), outcome(), market(observed_at=T - timedelta(minutes=1)))


def test_postgame_market_observation_rejected():
    with pytest.raises(ValueError, match="pregame"):
        evaluate(prediction(), outcome(), market(observed_at=T + timedelta(hours=2)))


def test_mismatched_market_rejected():
    with pytest.raises(ValueError, match="does not match"):
        evaluate(prediction(), outcome(), market(event_id="different"))


def test_mismatched_outcome_rejected():
    with pytest.raises(ValueError, match="does not match"):
        evaluate(prediction(), outcome(event_id="different"))


def test_outcome_before_game_rejected():
    with pytest.raises(ValueError, match="settle after"):
        evaluate(prediction(), outcome(settled_at=T))


def test_naive_timestamp_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        prediction(predicted_at=datetime(2026, 10, 21, 12))
