"""The preregistration boundary, and the guards that keep it from drifting from the code."""

from __future__ import annotations

import importlib

import pytest

from credit_audit.checks.reason_validity import DEFAULT_FLIP_DELTA
from credit_audit.stats.families import (
    PREREG_PATH,
    Estimand,
    Hypothesis,
    HypothesisTest,
    Preregistration,
    UndeclaredFamilyError,
    load_preregistration,
)
from credit_audit.types import Family, Relation

CHECK_CONSTANT_MODULES = (
    "credit_audit.interventions.pairs",
    "credit_audit.interventions.monotone",
    "credit_audit.checks.reason_validity",
    "credit_audit.checks.policy_adherence",
    "credit_audit.checks.invariance",
    "credit_audit.checks.serialization",
    "credit_audit.checks.counterfactual_bias",
)


@pytest.fixture(scope="module")
def prereg() -> Preregistration:
    return load_preregistration()


def _declared_check_constants() -> list[tuple[str, str, str]]:
    """Every ``CHECK_*`` constant the checks layer can emit, as (module, name, value)."""

    found: list[tuple[str, str, str]] = []
    for module_name in CHECK_CONSTANT_MODULES:
        module = importlib.import_module(module_name)
        for name in dir(module):
            if not name.startswith("CHECK_"):
                continue
            value = getattr(module, name)
            if isinstance(value, str):
                found.append((module_name, name, value))
    return sorted(set(found))


def test_document_parses_and_is_hashed(prereg):
    assert prereg.version == 1
    assert prereg.sha256.startswith("sha256:")
    assert prereg.alpha == 0.05
    assert prereg.fdr.q == 0.05
    assert prereg.bootstrap.resampling_unit == "cluster_id"
    assert prereg.pass_k.k == 5


def test_hash_tracks_the_file_on_disk(prereg):
    from credit_audit.ids import sha256_file

    assert prereg.sha256 == sha256_file(PREREG_PATH)


def test_every_check_the_code_can_emit_is_declared(prereg):
    """A check constant added to the code without a hypothesis fails here.

    Without this, a new check would silently score as `exploratory` forever and nobody
    would notice it never entered a BH group.
    """

    undeclared: list[str] = []
    for module_name, name, value in _declared_check_constants():
        if name.endswith("_PREFIX"):
            # Dynamic identifiers: the constant is a stem, the emitted check appends a
            # comparison label. The preregistration declares the stem with its separator.
            if prereg.hypothesis_for(f"{value}.example") is None:
                undeclared.append(f"{module_name}.{name} = {value!r}")
            continue
        if value in prereg.operational_checks:
            continue
        if prereg.hypothesis_for(value) is None:
            undeclared.append(f"{module_name}.{name} = {value!r}")
    assert not undeclared, "checks with no preregistered hypothesis: " + ", ".join(undeclared)


def test_every_hypothesis_targets_a_check_the_code_emits(prereg):
    """The reverse guard: a hypothesis for a check that no longer exists is dead weight."""

    constants = _declared_check_constants()
    emitted = {value for _, _, value in constants}
    prefixes = {f"{value}." for _, name, value in constants if name.endswith("_PREFIX")}
    orphans = [
        hypothesis.id
        for hypothesis in prereg.hypotheses
        if (hypothesis.check is not None and hypothesis.check not in emitted)
        or (hypothesis.check_prefix is not None and hypothesis.check_prefix not in prefixes)
    ]
    assert not orphans, f"hypotheses targeting checks the code never emits: {orphans}"


def test_declared_deltas_match_the_thresholds_the_checks_apply(prereg):
    """The preregistration owns the thresholds, so it must state the ones actually used.

    Reason repair applies `DEFAULT_FLIP_DELTA`; every other family relies on
    `PairedScore.relation_holds`'s zero-tolerance default. If either changes without the
    document changing, the published thresholds would describe a run that never happened.
    """

    for hypothesis in prereg.hypotheses:
        is_flip_test = (
            hypothesis.family is Family.REASON_REPAIR
            and hypothesis.test is HypothesisTest.MCNEMAR_EXACT
        )
        if is_flip_test:
            assert hypothesis.delta == DEFAULT_FLIP_DELTA, hypothesis.id
        else:
            assert hypothesis.delta == 0.0, hypothesis.id


def test_framing_is_undeclared_and_refused(prereg):
    """Framing interventions are deferred, so a FRAMING result is a bug, not a finding."""

    assert Family.FRAMING not in prereg.declared_families
    with pytest.raises(UndeclaredFamilyError, match="FRAMING"):
        prereg.resolve("framing.loss_gain", Family.FRAMING)


def test_undeclared_check_inside_a_declared_family_is_exploratory(prereg):
    resolution = prereg.resolve("monotonicity.brand_new_probe", Family.MONOTONE)
    assert resolution.hypothesis is None
    assert resolution.exploratory is True
    assert resolution.prereg is False
    assert resolution.estimand is Estimand.CHECK_FAILURE_RATE
    assert resolution.test is HypothesisTest.NONE


def test_operational_check_resolves_without_a_hypothesis(prereg):
    resolution = prereg.resolve("reason_validity.base_inapplicable", Family.REASON_REPAIR)
    assert resolution.operational is True
    assert resolution.exploratory is False
    assert resolution.prereg is False


def test_check_declared_under_a_different_family_is_a_contradiction(prereg):
    with pytest.raises(ValueError, match="declared under"):
        prereg.resolve("monotonicity.income_increase", Family.INVARIANCE)


def test_the_diagnostic_grid_is_declared_exploratory_before_the_run(prereg):
    """Declared exploratory up front, not demoted after seeing which cells moved."""

    resolution = prereg.resolve(
        "counterfactual_bias.diagnostic_intersection.groupA.female", Family.DEMOGRAPHIC
    )
    assert resolution.hypothesis is not None
    assert resolution.exploratory is True
    assert resolution.prereg is False
    assert resolution.hypothesis.test is HypothesisTest.NONE


def test_the_most_specific_declaration_wins(prereg):
    resolution = prereg.resolve("counterfactual_bias.recorded_sex", Family.DEMOGRAPHIC)
    assert resolution.hypothesis is not None
    assert resolution.hypothesis.id == "demo.recorded_sex"


def test_hypothesis_rejects_both_or_neither_target():
    for kwargs in (
        {"check": "a.b", "check_prefix": "a."},
        {},
    ):
        with pytest.raises(ValueError, match="exactly one of check/check_prefix"):
            Hypothesis(
                id="h",
                label="l",
                family=Family.MONOTONE,
                relation=Relation.NONDECREASING,
                delta=0.0,
                estimand=Estimand.CHECK_FAILURE_RATE,
                **kwargs,
            )


def test_forbidden_transition_requires_a_directional_relation():
    with pytest.raises(ValueError, match="forbids no single transition"):
        Hypothesis(
            id="h",
            label="l",
            family=Family.INVARIANCE,
            check="x.y",
            relation=Relation.INVARIANT,
            delta=0.0,
            estimand=Estimand.FORBIDDEN_TRANSITION_RATE,
        )


def test_paired_test_requires_a_paired_estimand():
    with pytest.raises(ValueError, match="paired test for an unpaired estimand"):
        Hypothesis(
            id="h",
            label="l",
            family=Family.POLICY_ADHERENCE,
            check="x.y",
            relation=Relation.UNCONSTRAINED,
            delta=0.0,
            estimand=Estimand.CHECK_FAILURE_RATE,
            test=HypothesisTest.MCNEMAR_EXACT,
        )


def test_forbidden_transition_maps_to_the_same_cell_monotonicity_counts():
    """`Hypothesis.forbidden_transition` must agree with `checks.monotonicity._violations`.

    Both answer "which matched transition is a violation" and they are computed in
    different modules; a divergence would silently change every monotonicity rate.
    """

    from credit_audit.checks.monotonicity import _violations
    from credit_audit.checks.paired import PairedScore

    score = PairedScore(
        planned_trials=4,
        matched_trials=4,
        base_completed=4,
        cf_completed=4,
        bilateral_incomplete=0,
        unilateral_incomplete=0,
        pair_completion_rate=1.0,
        base_approve_rate=0.5,
        cf_approve_rate=0.5,
        effect=0.0,
        adverse_to_approve=1,
        approve_to_adverse=3,
        reason_signature_changes=0,
        decision_signature_changes=4,
    )
    for relation, expected in (
        (Relation.NONDECREASING, 3),
        (Relation.NONINCREASING, 1),
    ):
        hypothesis = Hypothesis(
            id="h",
            label="l",
            family=Family.MONOTONE,
            check="x.y",
            relation=relation,
            delta=0.0,
            estimand=Estimand.FORBIDDEN_TRANSITION_RATE,
        )
        key = hypothesis.forbidden_transition
        assert key is not None
        assert score.observed()[key] == expected
        assert _violations(score, relation)[0] == expected


def test_bootstrap_policy_refuses_to_drop_clustering():
    from credit_audit.stats.families import BootstrapPolicy

    with pytest.raises(ValueError, match="must be cluster_id"):
        BootstrapPolicy(
            method="BCa", B=100, resampling_unit="pair_id", fallback="percentile", seed=1
        )
