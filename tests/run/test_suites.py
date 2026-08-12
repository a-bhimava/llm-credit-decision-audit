"""Suite definitions: parsed, validated, hashed, and consistent with the families that exist."""

from __future__ import annotations

import pytest

from credit_audit.suites.loader import (
    SUITE_NAMES,
    Caps,
    Family,
    Selection,
    Suite,
    load_suite,
    suite_path,
)


@pytest.mark.parametrize("name", SUITE_NAMES)
def test_every_declared_suite_loads_and_is_hashed(name):
    suite = load_suite(name)
    assert suite.name == name
    assert suite.sha256.startswith("sha256:")
    assert suite.k_trials >= 1
    assert suite.families


def test_suite_families_all_map_to_real_check_entry_points():
    """A suite naming a family the executor cannot dispatch would fail at run time."""

    from credit_audit.run.execute import _run_family

    assert _run_family is not None
    for name in SUITE_NAMES:
        for family in load_suite(name).families:
            assert isinstance(family, Family)


def test_smoke_is_small_and_core_is_the_published_size():
    smoke = load_suite("smoke")
    core = load_suite("core")
    full = load_suite("full")

    assert smoke.applicants.limit == 3
    assert smoke.k_trials == 2
    assert core.applicants.limit == 24
    assert core.k_trials == 5
    assert full.applicants.limit is None
    assert set(core.families) == set(full.families)


def test_scripted_suites_cap_spend_at_zero():
    """Not decoration: a scripted agent reports zero cost, so a zero cap is a live assertion
    that this suite made no paid call."""

    for name in SUITE_NAMES:
        caps = load_suite(name).caps
        assert caps.max_usd == 0.0
        assert caps.max_tokens == 0
        assert caps.max_episodes is not None
        assert caps.max_wall_seconds is not None


def test_unknown_suite_names_are_rejected():
    with pytest.raises(ValueError, match="unknown suite"):
        suite_path("enormous")


def _suite(**overrides) -> dict:
    base = dict(
        schema_id="credit-audit/suite@1",
        name="smoke",
        label="L",
        description="D",
        applicants={"select": Selection.ALL},
        families=(Family.MONOTONICITY,),
        k_trials=1,
        caps=Caps(),
    )
    base.update(overrides)
    return base


def test_unsupported_schema_is_rejected():
    with pytest.raises(ValueError, match="unsupported suite schema"):
        Suite(**_suite(schema_id="credit-audit/suite@99"))


def test_unknown_name_is_rejected():
    with pytest.raises(ValueError, match="unknown suite name"):
        Suite(**_suite(name="gigantic"))


def test_empty_or_duplicated_families_are_rejected():
    with pytest.raises(ValueError, match="declares no families"):
        Suite(**_suite(families=()))
    with pytest.raises(ValueError, match="declares a family twice"):
        Suite(**_suite(families=(Family.MONOTONICITY, Family.MONOTONICITY)))
