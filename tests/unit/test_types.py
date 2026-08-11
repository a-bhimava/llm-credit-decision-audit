"""The four load-bearing invariants of the type system.

These are not style tests. Each one guards a specific way the project's central claim could
quietly become false.
"""

from __future__ import annotations

import inspect
from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from credit_audit import types as T
from credit_audit.ids import content_id, trajectory_content_id


def _all_records() -> list[type[BaseModel]]:
    return [
        obj
        for _, obj in inspect.getmembers(T, inspect.isclass)
        if issubclass(obj, BaseModel) and obj is not BaseModel and obj is not T.Frozen
    ]


def _facts(**overrides) -> T.FinancialFacts:
    base = dict(
        annual_income_cents=6_000_000,
        monthly_debt_cents=150_000,
        loan_amount_cents=25_000_000,
        property_value_cents=30_000_000,
        loan_term_months=360,
        credit_score=720,
        open_tradelines=8,
        revolving_balance_cents=400_000,
        revolving_limit_cents=2_000_000,
        delinq_30d_24m=0,
        delinq_60d_24m=0,
        delinq_90p_24m=0,
        oldest_tradeline_months=120,
        inquiries_6m=1,
        employment_months=48,
        employment_status=T.EmploymentStatus.FULL_TIME,
        income_documented=True,
    )
    base.update(overrides)
    return T.FinancialFacts(**base)


def _presentation(**overrides) -> T.Presentation:
    base = dict(applicant_name="Pat Doe", employer_name="Acme Co", employer_prestige_tier=3)
    base.update(overrides)
    return T.Presentation(**base)


# -- Invariant 2: derived quantities are never stored -----------------------------------


DERIVED_NAMES = ("dti", "cltv", "utilization", "monthly_income_cents", "delinquencies_total")


def test_no_derived_stored_fields():
    """Derived quantities must be properties, not fields.

    If ``dti`` were stored, a repair that raises income would leave a stale ratio behind and
    hand the agent an internally incoherent record -- which it can notice and react to,
    silently contaminating every counterfactual.
    """
    for name in DERIVED_NAMES:
        assert name not in T.FinancialFacts.model_fields, f"{name} must be a property, not a field"
        assert isinstance(getattr(T.FinancialFacts, name), property)


def test_derived_recompute_from_primitives():
    """Raising income lowers DTI automatically. This is the whole point of invariant 2."""
    before = _facts(annual_income_cents=6_000_000, monthly_debt_cents=150_000)
    assert before.dti == Decimal("0.3000")

    after = before.model_copy(update={"annual_income_cents": 12_000_000})
    assert after.dti == Decimal("0.1500")
    assert after.monthly_debt_cents == before.monthly_debt_cents


@pytest.mark.parametrize(
    ("income", "debt", "expected"),
    [
        (6_000_000, 150_000, "0.3000"),
        (6_000_000, 215_000, "0.4300"),  # exactly on a typical threshold
        (0, 100_000, "1.0000"),  # zero income sentinel: always a breach
    ],
)
def test_dti_is_exact_decimal(income, debt, expected):
    """Threshold comparisons must be exact. A float DTI eventually mis-fires a repair."""
    facts = _facts(annual_income_cents=income, monthly_debt_cents=debt)
    assert facts.dti == Decimal(expected)
    assert isinstance(facts.dti, Decimal)


def test_unsecured_product_has_zero_cltv():
    assert _facts(property_value_cents=0).cltv == Decimal("0.0000")


# -- Invariant 1: money is int cents, ratios are Decimal --------------------------------


def test_money_fields_are_int_cents():
    """Every ``*_cents`` field on every record is an int. No float money anywhere."""
    for record in _all_records():
        for name, field in record.model_fields.items():
            if name.endswith("_cents"):
                assert field.annotation in (int, int | None), (
                    f"{record.__name__}.{name} must be int cents, got {field.annotation}"
                )


def test_financial_facts_has_no_float_fields():
    """Financial quantities are never float.

    Statistical quantities elsewhere (p-values, effect sizes, ``mapping_confidence``) are
    legitimately float and are deliberately out of scope for this test.
    """
    for name, field in T.FinancialFacts.model_fields.items():
        assert field.annotation is not float, f"FinancialFacts.{name} must not be float"


def test_ratio_properties_are_quantized_to_4dp():
    facts = _facts(annual_income_cents=7_777_777, monthly_debt_cents=123_457)
    for value in (facts.dti, facts.cltv, facts.utilization):
        assert value == value.quantize(T.RATIO_EXP)


# -- Invariant 3: facts / presentation independence -------------------------------------


def test_presentation_change_leaves_facts_hash_identical():
    """The load-bearing guarantee behind every bias arm.

    "Identical financial profile, only the name changed" must be structurally true, not a
    claim the reader is asked to trust.
    """
    facts = _facts()
    a = T.Applicant(
        applicant_id="APP-1",
        facts=facts,
        presentation=_presentation(applicant_name="Emily Chen", employer_prestige_tier=1),
        provenance=T.Provenance(generator_seed=1, generator_version="test"),
    )
    b = a.model_copy(
        update={
            "presentation": _presentation(applicant_name="Darius Johnson", employer_prestige_tier=5)
        }
    )

    assert content_id(a.facts) == content_id(b.facts)
    assert content_id(a.presentation) != content_id(b.presentation)


def test_facts_change_leaves_presentation_hash_identical():
    presentation = _presentation()
    a = T.Applicant(
        applicant_id="APP-1",
        facts=_facts(annual_income_cents=6_000_000),
        presentation=presentation,
        provenance=T.Provenance(generator_seed=1, generator_version="test"),
    )
    b = a.model_copy(update={"facts": _facts(annual_income_cents=9_000_000)})

    assert content_id(a.presentation) == content_id(b.presentation)
    assert content_id(a.facts) != content_id(b.facts)


def test_intervention_declares_its_layer():
    """Every intervention must say which half of the applicant it may touch."""
    assert "layer" in T.InterventionSpec.model_fields
    assert T.InterventionSpec.model_fields["layer"].is_required()


# -- Invariant 4: pair and source-cluster IDs are required ------------------------------


def test_test_result_requires_pair_and_cluster_ids():
    """A contrast and its source experimental unit are distinct required identities."""
    assert T.TestResult.model_fields["pair_id"].is_required()
    assert T.TestResult.model_fields["cluster_id"].is_required()

    with pytest.raises(ValidationError):
        T.TestResult(
            test_id="t1",
            check="reason_validity.necessity_loo",
            family=T.Family.REASON_REPAIR,
            applicant_id="APP-1",
            status=T.TestStatus.FAIL,
        )

    with pytest.raises(ValidationError):
        T.TestResult(
            test_id="t1",
            check="reason_validity.necessity_loo",
            family=T.Family.REASON_REPAIR,
            applicant_id="APP-1",
            status=T.TestStatus.FAIL,
            pair_id="pair-1",
        )

    with pytest.raises(ValidationError, match="must be distinct"):
        T.TestResult(
            test_id="t1",
            check="reason_validity.necessity_loo",
            family=T.Family.REASON_REPAIR,
            applicant_id="APP-1",
            status=T.TestStatus.FAIL,
            pair_id="same-id",
            cluster_id="same-id",
        )


# -- General record hygiene -------------------------------------------------------------


def test_records_are_frozen_and_forbid_extras():
    facts = _facts()
    with pytest.raises(ValidationError):
        facts.credit_score = 800  # type: ignore[misc]
    with pytest.raises(ValidationError):
        T.Provenance(generator_seed=1, generator_version="v", nonexistent_field=True)


def test_all_records_inherit_frozen_base():
    for record in _all_records():
        assert record.model_config.get("frozen") is True, f"{record.__name__} is not frozen"


def test_dict_fields_are_actually_immutable_and_hashable():
    """frozen=True alone only blocks attribute reassignment -- a plain dict field's
    contents could still be mutated in place, and a plain dict is unhashable regardless.
    FrozenDict closes both gaps; this test is the demonstration that it actually does."""
    call = T.ToolCall(
        call_id="c1",
        turn_index=1,
        step=0,
        name="x",
        arguments={"a": [{"nested": [1, 2]}]},
        result={"r": {"items": [1]}},
    )
    assert isinstance(call.arguments, T.FrozenDict)
    assert isinstance(call.arguments["a"], tuple)
    assert isinstance(call.arguments["a"][0], T.FrozenDict)
    with pytest.raises(TypeError):
        call.arguments["a"] = 999  # type: ignore[index]
    with pytest.raises(TypeError):
        call.arguments["a"][0]["nested"] = ()  # type: ignore[index]
    hash(call)  # must not raise

    spec = T.InterventionSpec(
        intervention_id="i1",
        family=T.Family.REASON_REPAIR,
        name="n",
        layer=T.Layer.FACTS,
        params={"k": [{"v": [1, 2]}]},
    )
    assert isinstance(spec.params, T.FrozenDict)
    hash(spec)

    result = T.TestResult(
        test_id="t1",
        check="x",
        family=T.Family.REASON_REPAIR,
        applicant_id="APP-1",
        status=T.TestStatus.PASS,
        pair_id="p1",
        cluster_id="cluster-1",
        observed={"nested": [{"values": [1, 2]}]},
    )
    hash(result)
    with pytest.raises(TypeError):
        result.observed["nested"][0]["values"] = ()  # type: ignore[index]


def test_frozen_dict_behaves_like_a_read_only_dict():
    fd = T.FrozenDict({"a": 1, "b": 2})
    assert fd["a"] == 1
    assert dict(fd) == {"a": 1, "b": 2}
    assert {**fd} == {"a": 1, "b": 2}
    assert fd == {"a": 1, "b": 2}
    assert sorted(fd.items()) == [("a", 1), ("b", 2)]
    assert hash(fd) == hash(T.FrozenDict({"b": 2, "a": 1}))  # order-independent


def test_freeze_thaw_roundtrip_uses_json_containers():
    original = {"a": [{"b": [1, 2]}], "c": None}
    frozen = T.freeze_json(original)
    assert isinstance(frozen, T.FrozenDict)
    assert T.thaw_json(frozen) == original
    assert isinstance(T.thaw_json(frozen)["a"], list)


def test_frozen_payload_rejects_shallow_frozen_external_models():
    class ShallowFrozen(BaseModel):
        model_config = {"frozen": True}
        values: list[int]

    with pytest.raises(TypeError, match="unsupported mutable"):
        T.FrozenDict({"nested": ShallowFrozen(values=[1])})

    raw = bytearray(b"abc")
    payload = T.FrozenDict({"bytes": raw})
    raw[0] = ord("z")
    assert payload["bytes"] == b"abc"
    hash(payload)


def test_frozen_base_recursively_freezes_legacy_dict_annotations(policy):
    """Policy records retain dict annotations, but the shared Frozen base seals them."""
    assert isinstance(policy.fields, T.FrozenDict)
    assert isinstance(policy.process.required_tools_before_code, T.FrozenDict)
    with pytest.raises(TypeError):
        policy.fields["credit_score"] = policy.fields["credit_score"]  # type: ignore[index]
    hash(policy)


def test_episode_id_is_stable_and_render_layer_exists():
    key = T.EpisodeKey(
        applicant_id="APP-1",
        applicant_content_id="content-1",
        arm_id="control",
        render_id=T.RenderMode.TABLE,
        trial_index=0,
        model_id="test",
        prompt_hash="p",
        input_hash="input-1",
        seed=1,
    )
    assert key.episode_id == T.EpisodeKey(**key.model_dump()).episode_id
    assert T.Layer.RENDER.value == "render"

    trajectory_id = trajectory_content_id(
        episode_id=key.episode_id,
        messages=(),
        tool_calls=(),
        decision=None,
        termination=T.Termination.STOP,
    )
    trajectory = T.Trajectory(
        episode_id=key.episode_id,
        trajectory_id=trajectory_id,
        key=key,
        termination=T.Termination.STOP,
    )
    with pytest.raises(ValidationError, match="episode_id"):
        T.Trajectory(**{**trajectory.model_dump(), "episode_id": "forged"})
    with pytest.raises(ValidationError, match="trajectory_id"):
        T.Trajectory(**{**trajectory.model_dump(), "trajectory_id": "forged"})


def test_trajectory_terminal_state_and_decision_must_agree():
    key = T.EpisodeKey(
        applicant_id="APP-1",
        applicant_content_id="content-1",
        arm_id="control",
        render_id=T.RenderMode.TABLE,
        trial_index=0,
        model_id="test",
        prompt_hash="p",
        input_hash="input-1",
        seed=1,
    )
    submitted_without_decision_id = trajectory_content_id(
        episode_id=key.episode_id,
        messages=(),
        tool_calls=(),
        decision=None,
        termination=T.Termination.SUBMITTED,
    )
    with pytest.raises(ValidationError, match="requires a decision"):
        T.Trajectory(
            episode_id=key.episode_id,
            trajectory_id=submitted_without_decision_id,
            key=key,
            termination=T.Termination.SUBMITTED,
        )

    decision = T.Decision(outcome=T.DecisionOutcome.APPROVE, is_adverse_action=False)
    stopped_with_decision_id = trajectory_content_id(
        episode_id=key.episode_id,
        messages=(),
        tool_calls=(),
        decision=decision,
        termination=T.Termination.STOP,
    )
    with pytest.raises(ValidationError, match="cannot carry a decision"):
        T.Trajectory(
            episode_id=key.episode_id,
            trajectory_id=stopped_with_decision_id,
            key=key,
            decision=decision,
            termination=T.Termination.STOP,
        )

    submitted_without_call_id = trajectory_content_id(
        episode_id=key.episode_id,
        messages=(),
        tool_calls=(),
        decision=decision,
        termination=T.Termination.SUBMITTED,
    )
    with pytest.raises(ValidationError, match="successful submit_decision"):
        T.Trajectory(
            episode_id=key.episode_id,
            trajectory_id=submitted_without_call_id,
            key=key,
            decision=decision,
            termination=T.Termination.SUBMITTED,
        )


def test_ratio_properties_are_isolated_from_the_ambient_decimal_context():
    """FinancialFacts.dti/cltv/utilization must not be able to raise (or silently lose
    precision) just because some other imported library mutated the global Decimal
    context -- see FIXED_DECIMAL_CTX's docstring. Mirrors the exact repro used to find
    this: getcontext().prec = 3 previously made facts.dti raise InvalidOperation."""
    import decimal

    facts = _facts(annual_income_cents=6_000_000, monthly_debt_cents=60_000)
    expected_dti = facts.dti
    expected_cltv = facts.cltv
    expected_utilization = facts.utilization
    original_prec = decimal.getcontext().prec
    try:
        decimal.getcontext().prec = 3
        assert facts.dti == expected_dti
        assert facts.cltv == expected_cltv
        assert facts.utilization == expected_utilization
    finally:
        decimal.getcontext().prec = original_prec


def test_field_constraints_reject_impossible_values():
    with pytest.raises(ValidationError):
        _facts(credit_score=200)  # below the 300 floor
    with pytest.raises(ValidationError):
        _facts(annual_income_cents=-1)
    with pytest.raises(ValidationError):
        _facts(loan_amount_cents=0)  # must be > 0
    with pytest.raises(ValidationError):
        _presentation(employer_prestige_tier=9)


def test_reason_codes_include_the_zero_cost_failures():
    """Two codes fail on their face, with no counterfactual and no API call:
    a non-specific "internal policy" reason, and a factor the record cannot contain."""
    assert T.ReasonCode.NON_SPECIFIC_INTERNAL_POLICY
    assert T.ReasonCode.OUT_OF_SCHEMA_FACTOR


def test_default_k_trials_is_five():
    """k=5 everywhere. The two-stage screen-then-confirm design was dropped: it existed only as
    a cost control, and re-running only failures biases every rate upward."""
    manifest_field = T.RunManifest.model_fields["k_trials"]
    assert manifest_field.default == 5
