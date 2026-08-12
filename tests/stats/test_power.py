"""MDE and power for the paired design, including the degenerate designs that have none."""

from __future__ import annotations

import pytest

from credit_audit.stats.power import analyze_power, mcnemar_mde, mcnemar_power


def test_power_at_no_effect_is_the_nominal_level():
    assert mcnemar_power(n_pairs=500, discordance_rate=0.2, effect=0.0, alpha=0.05) == 0.05


def test_power_increases_with_sample_size():
    small = mcnemar_power(n_pairs=100, discordance_rate=0.2, effect=0.08)
    large = mcnemar_power(n_pairs=1000, discordance_rate=0.2, effect=0.08)
    assert small is not None and large is not None
    assert large > small


def test_power_increases_with_effect_size():
    weak = mcnemar_power(n_pairs=300, discordance_rate=0.3, effect=0.05)
    strong = mcnemar_power(n_pairs=300, discordance_rate=0.3, effect=0.20)
    assert weak is not None and strong is not None
    assert strong > weak


def test_effect_larger_than_the_discordance_that_produces_it_is_impossible():
    """|c - b| can never exceed b + c, so such a design is not merely underpowered."""

    assert mcnemar_power(n_pairs=200, discordance_rate=0.1, effect=0.3) is None


def test_degenerate_designs_report_none():
    assert mcnemar_power(n_pairs=0, discordance_rate=0.2, effect=0.1) is None
    assert mcnemar_power(n_pairs=200, discordance_rate=0.0, effect=0.1) is None
    assert mcnemar_mde(n_pairs=200, discordance_rate=0.0) is None


def test_mde_is_the_effect_that_achieves_target_power():
    mde = mcnemar_mde(n_pairs=400, discordance_rate=0.25, target_power=0.80)
    assert mde is not None
    at_mde = mcnemar_power(n_pairs=400, discordance_rate=0.25, effect=mde)
    just_below = mcnemar_power(n_pairs=400, discordance_rate=0.25, effect=mde * 0.9)
    assert at_mde == pytest.approx(0.80, abs=1e-3)
    assert just_below is not None and just_below < 0.80


def test_mde_shrinks_as_the_run_grows():
    small = mcnemar_mde(n_pairs=100, discordance_rate=0.25)
    large = mcnemar_mde(n_pairs=2000, discordance_rate=0.25)
    assert small is not None and large is not None
    assert large < small


def test_a_run_too_small_to_detect_anything_says_so():
    """`None` rather than an MDE larger than the design can express."""

    assert mcnemar_mde(n_pairs=4, discordance_rate=0.1) is None


def test_analysis_carries_the_preregistered_parameters():
    analysis = analyze_power(
        check="monotonicity.income_increase",
        n_pairs=300,
        discordance_rate=0.2,
        observed_effect=0.15,
        alpha=0.05,
        target_power=0.80,
    )
    assert analysis.check == "monotonicity.income_increase"
    assert analysis.alpha == 0.05
    assert analysis.target_power == 0.80
    assert analysis.assumed_discordance == 0.2
    assert analysis.mde is not None
    assert analysis.achieved_power_at_observed is not None


def test_analysis_without_discordance_reports_no_mde():
    analysis = analyze_power(check="x", n_pairs=0, discordance_rate=None)
    assert analysis.mde is None
    assert analysis.assumed_discordance is None


def test_invalid_inputs_are_rejected():
    with pytest.raises(ValueError, match="target_power"):
        mcnemar_mde(n_pairs=100, discordance_rate=0.2, target_power=1.0)
    with pytest.raises(ValueError, match="discordance_rate"):
        mcnemar_power(n_pairs=100, discordance_rate=1.5, effect=0.1)
