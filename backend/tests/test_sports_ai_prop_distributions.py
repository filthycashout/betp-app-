from __future__ import annotations

import math

import pytest

from sports_ai.props.distributions import fit_count_distribution, line_probabilities
from sports_ai.props.rate import estimate_rate, project_count_prop


def test_rate_estimate_uses_paired_total_opportunity() -> None:
    result = estimate_rate([5, 6, 4], [30, 30, 20])
    assert result.sample_size == 3
    assert result.total_stat == 15
    assert result.total_opportunity == 80
    assert result.rate_per_opportunity == pytest.approx(15 / 80)


def test_poisson_selected_when_variance_is_not_materially_overdispersed() -> None:
    distribution = fit_count_distribution([4, 5, 6, 5, 5], projected_mean=5.5)
    assert distribution.family == "poisson"
    assert distribution.mean == 5.5
    assert distribution.variance == 5.5


def test_negative_binomial_selected_for_overdispersed_samples() -> None:
    distribution = fit_count_distribution([0, 1, 2, 8, 10, 12], projected_mean=6.0)
    assert distribution.family == "negative_binomial"
    assert distribution.variance > distribution.mean
    assert distribution.nb_r is not None
    assert distribution.nb_p is not None


def test_half_line_has_no_push_and_probabilities_sum_to_one() -> None:
    distribution = fit_count_distribution([4, 5, 6, 5, 5], projected_mean=5.0)
    probabilities = line_probabilities(distribution, 4.5)
    assert probabilities["push"] == 0.0
    assert probabilities["over_win"] + probabilities["under_win"] == pytest.approx(1.0)


def test_integer_line_has_push_probability() -> None:
    distribution = fit_count_distribution([4, 5, 6, 5, 5], projected_mean=5.0)
    probabilities = line_probabilities(distribution, 5.0)
    expected_push = math.exp(-5) * (5**5) / math.factorial(5)
    assert probabilities["push"] == pytest.approx(expected_push)
    assert sum(probabilities.values()) == pytest.approx(1.0)


def test_projected_prop_is_explicitly_uncalibrated_and_ineligible() -> None:
    result = project_count_prop(
        stat_samples=[4, 5, 6, 5, 7],
        opportunity_samples=[30, 31, 34, 32, 36],
        projected_opportunity=35,
        line=5.5,
        side="over",
        american_odds=-110,
    )
    assert result["status"] == "RESEARCH_UNCALIBRATED"
    assert result["calibrated"] is False
    assert result["promotion_passed"] is False
    assert result["recommendation_eligible"] is False
    assert 0 < result["win_probability"] < 1
    assert result["push_probability"] == 0.0
    assert result["research_expected_value"] is not None
    assert result["governance_reason"] == "OOF_CALIBRATION_AND_MODEL_PROMOTION_REQUIRED"


def test_push_aware_ev_does_not_treat_push_as_loss() -> None:
    integer = project_count_prop(
        stat_samples=[4, 5, 6, 5, 7],
        opportunity_samples=[30, 31, 34, 32, 36],
        projected_opportunity=35,
        line=5.0,
        side="over",
        american_odds=100,
    )
    half = project_count_prop(
        stat_samples=[4, 5, 6, 5, 7],
        opportunity_samples=[30, 31, 34, 32, 36],
        projected_opportunity=35,
        line=5.5,
        side="over",
        american_odds=100,
    )
    assert integer["push_probability"] > 0
    assert half["push_probability"] == 0


def test_insufficient_sample_fails_closed() -> None:
    with pytest.raises(ValueError, match="at least 3"):
        project_count_prop(
            stat_samples=[4, 5],
            opportunity_samples=[30, 31],
            projected_opportunity=32,
            line=4.5,
            side="over",
        )
