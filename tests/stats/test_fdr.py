"""Benjamini-Hochberg: the step-up behaviour, including the case people get wrong."""

from __future__ import annotations

import pytest

from credit_audit.stats.fdr import benjamini_hochberg, benjamini_hochberg_group


def test_adjusted_values_follow_the_definition():
    p_values = [0.001, 0.01, 0.04, 0.5]
    q_values = benjamini_hochberg(p_values, q=0.05)
    assert q_values == pytest.approx((0.004, 0.02, 0.05333333, 0.5))


def test_order_of_the_input_is_preserved():
    shuffled = [0.5, 0.001, 0.04, 0.01]
    q_values = benjamini_hochberg(shuffled, q=0.05)
    assert q_values[1] == pytest.approx(0.004)
    assert q_values[0] == pytest.approx(0.5)


def test_q_values_are_monotone_in_p():
    p_values = [0.001, 0.002, 0.9, 0.91, 0.92]
    q_values = benjamini_hochberg(p_values, q=0.05)
    ordered = [q for _, q in sorted(zip(p_values, q_values, strict=True))]
    assert ordered == sorted(ordered)


def test_a_small_p_is_rescued_by_a_larger_one_further_up_the_ranking():
    """The step-up property: BH rejects everything below the largest passing rank.

    Alone, p = 0.03 with m = 4 would not clear 0.05. Here rank 4 clears the line at
    0.04 <= 4/4 * 0.05, so every smaller p-value is rejected too -- including one that a
    naive per-hypothesis comparison against i/m * q would have kept.
    """

    group = benjamini_hochberg_group(
        {"a": 0.01, "b": 0.02, "c": 0.03, "d": 0.04}, group="F", q=0.05
    )
    assert group.n_rejected == 4
    assert all(result.rejected for result in group.results)


def test_uniformly_null_p_values_reject_nothing():
    group = benjamini_hochberg_group(
        {f"h{i}": p for i, p in enumerate([0.2, 0.4, 0.6, 0.8, 0.95])}, group="F", q=0.05
    )
    assert group.n_rejected == 0


def test_empty_group_is_well_defined():
    assert benjamini_hochberg([], q=0.05) == ()
    group = benjamini_hochberg_group({}, group="F", q=0.05)
    assert group.n_hypotheses == 0
    assert group.n_rejected == 0


def test_group_reports_ranks_and_size():
    group = benjamini_hochberg_group({"a": 0.5, "b": 0.001}, group="F", q=0.05)
    by_key = {result.key: result for result in group.results}
    assert by_key["b"].rank == 1
    assert by_key["a"].rank == 2
    assert all(result.n_hypotheses == 2 for result in group.results)


def test_duplicate_keys_are_rejected():
    with pytest.raises(ValueError, match="duplicate hypothesis keys"):
        benjamini_hochberg_group([("a", 0.1), ("a", 0.2)], group="F", q=0.05)


def test_invalid_inputs_are_rejected():
    with pytest.raises(ValueError, match="p-value outside"):
        benjamini_hochberg([1.5], q=0.05)
    with pytest.raises(ValueError, match="q must lie"):
        benjamini_hochberg([0.1], q=1.0)
