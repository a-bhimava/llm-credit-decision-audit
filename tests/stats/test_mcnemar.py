"""Exact McNemar: hand-checkable values, and the denominators it refuses to mix."""

from __future__ import annotations

import pytest

from credit_audit.stats.mcnemar import mcnemar_exact


def test_no_discordance_is_no_evidence():
    result = mcnemar_exact(0, 0, n_pairs=40)
    assert result.p_exact == 1.0
    assert result.p_mid == 1.0
    assert result.discordant_rate == 0.0
    assert result.net_rate == 0.0
    assert result.concordant == 40


def test_all_flips_in_one_direction_matches_the_binomial_by_hand():
    """Ten flips, all the same way: two-sided exact p is 2 * 0.5**10."""

    result = mcnemar_exact(0, 10, n_pairs=10)
    assert result.p_exact == pytest.approx(2 * 0.5**10)
    assert result.net_rate == 1.0
    assert result.discordant_rate == 1.0


def test_symmetric_counts_cannot_reject():
    result = mcnemar_exact(7, 7, n_pairs=100)
    assert result.p_exact == 1.0
    assert result.net_rate == 0.0
    assert result.discordant_rate == pytest.approx(0.14)


def test_direction_does_not_change_the_two_sided_p():
    assert mcnemar_exact(2, 9, n_pairs=50).p_exact == mcnemar_exact(9, 2, n_pairs=50).p_exact


def test_mid_p_is_strictly_less_than_exact_when_there_is_discordance():
    """Mid-p removes half the point mass at the observed value, so it is always smaller."""

    result = mcnemar_exact(3, 12, n_pairs=60)
    assert 0.0 < result.p_mid < result.p_exact <= 1.0


def test_net_and_discordant_rates_use_the_matched_denominator():
    result = mcnemar_exact(2, 6, n_pairs=200)
    assert result.discordant_rate == pytest.approx(8 / 200)
    assert result.net_rate == pytest.approx(4 / 200)
    assert result.n_discordant == 8


def test_zero_pairs_reports_no_rate_rather_than_zero():
    result = mcnemar_exact(0, 0, n_pairs=0)
    assert result.discordant_rate is None
    assert result.net_rate is None


def test_discordant_pairs_cannot_exceed_matched_pairs():
    """A mixed denominator would deflate every rate; it raises instead of rescaling."""

    with pytest.raises(ValueError, match="different denominators"):
        mcnemar_exact(5, 5, n_pairs=9)


def test_negative_counts_are_rejected():
    with pytest.raises(ValueError, match="non-negative"):
        mcnemar_exact(-1, 3, n_pairs=10)
