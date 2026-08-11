"""Unit tests for matched causal reason-validity scoring."""

from __future__ import annotations

import pytest

from credit_audit.checks.paired import (
    OutcomeClass,
    classify_trajectory,
    score_paired_trajectories,
)
from credit_audit.checks.reason_validity import (
    CHECK_BASE_INAPPLICABLE,
    _approve_rate,
    _canonical_cited_reasons,
    _clamped_fields,
    _completion_rate,
    score_reason_validity,
)
from credit_audit.ids import (
    applicant_content_id,
    derive_seed,
    episode_input_hash,
    trajectory_content_id,
)
from credit_audit.interventions.apply import apply_interventions
from credit_audit.interventions.pairs import (
    CHECK_FABRICATION,
    CHECK_JOINT_SUFFICIENCY,
    CHECK_NECESSITY_LOO,
    CHECK_OMISSION_SCAN,
)
from credit_audit.interventions.pairs import (
    build_counterfactual_specs as _build_counterfactual_specs,
)
from credit_audit.policy.loader import load_policy
from credit_audit.policy.oracle import evaluate
from credit_audit.render.reference import applicant_reference_for
from credit_audit.render.registry import render_application
from credit_audit.types import (
    Applicant,
    Decision,
    DecisionOutcome,
    EmploymentStatus,
    EpisodeKey,
    FinancialFacts,
    MappingMethod,
    Message,
    ParseStatus,
    Presentation,
    Provenance,
    ReasonCode,
    RenderMode,
    RequestedToolCall,
    StatedReason,
    Termination,
    ToolCall,
    Trajectory,
)
from credit_audit.types import TestStatus as ResultStatus

_BASE_KWARGS = dict(
    annual_income_cents=6_000_000,
    monthly_debt_cents=60_000,
    loan_amount_cents=800_000,
    property_value_cents=0,
    loan_term_months=48,
    credit_score=740,
    open_tradelines=6,
    revolving_balance_cents=200_000,
    revolving_limit_cents=1_000_000,
    delinq_30d_24m=0,
    delinq_60d_24m=0,
    delinq_90p_24m=0,
    oldest_tradeline_months=96,
    inquiries_6m=1,
    employment_months=60,
    employment_status=EmploymentStatus.FULL_TIME,
    income_documented=True,
)


def _facts(**overrides) -> FinancialFacts:
    values = dict(_BASE_KWARGS)
    values.update(overrides)
    return FinancialFacts(**values)


def _applicant(applicant_id: str, facts: FinancialFacts) -> Applicant:
    return Applicant(
        applicant_id=applicant_id,
        facts=facts,
        presentation=Presentation(
            applicant_name="Pat Doe", employer_name="Acme", employer_prestige_tier=2
        ),
        provenance=Provenance(generator_seed=1, generator_version="test"),
    )


def build_counterfactual_specs(applicant_id, facts, cited, decision, policy):
    return _build_counterfactual_specs(
        _applicant(applicant_id, facts),
        cited,
        decision,
        policy,
        render_mode=RenderMode.TABLE,
    )


def _reason(code: ReasonCode, rank: int = 1) -> StatedReason:
    return StatedReason(
        rank=rank,
        raw_text=code.value,
        code=code,
        mapping_method=MappingMethod.STRUCTURED,
        mapping_confidence=1.0,
    )


def _traj(
    trial_index: int,
    outcome: DecisionOutcome | None,
    stated_reasons: tuple[StatedReason, ...] = (),
    *,
    arm_id: str = "control",
    termination: Termination = Termination.SUBMITTED,
    is_adverse: bool | None = None,
    seed: int | None = None,
    evidence_applicant: Applicant | None = None,
    policy=None,
    seed_group: str | None = None,
) -> Trajectory:
    if evidence_applicant is None:
        applicant_id = "APP-X"
        evidence_content_id = f"content-{arm_id}"
        input_hash = f"input-{arm_id}"
    else:
        if policy is None:
            raise ValueError("policy is required with evidence_applicant")
        applicant_id = evidence_applicant.applicant_id
        evidence_content_id = applicant_content_id(evidence_applicant)
        application_text = render_application(evidence_applicant, RenderMode.TABLE, policy)
        input_hash = episode_input_hash(
            evidence_applicant,
            application_text=application_text,
            applicant_ref=applicant_reference_for(evidence_applicant),
            render_mode=RenderMode.TABLE,
        )
    if seed is None:
        seed = derive_seed(1729, seed_group, trial_index) if seed_group is not None else trial_index
    key = EpisodeKey(
        applicant_id=applicant_id,
        applicant_content_id=evidence_content_id,
        arm_id=arm_id,
        render_id=RenderMode.TABLE,
        trial_index=trial_index,
        model_id="test",
        prompt_hash="test-prompt",
        input_hash=input_hash,
        seed=seed,
    )
    decision = None
    if outcome is not None and termination is Termination.SUBMITTED:
        adverse = is_adverse if is_adverse is not None else outcome is DecisionOutcome.DENY
        decision = Decision(
            outcome=outcome,
            stated_reasons=stated_reasons,
            parse_status=ParseStatus.STRUCTURED,
            is_adverse_action=adverse,
        )
    if decision is not None:
        call_id = f"submit-{trial_index}"
        arguments = {"outcome": outcome.value if outcome is not None else ""}
        requested = RequestedToolCall(
            call_id=call_id,
            name="submit_decision",
            arguments=arguments,
        )
        messages = (
            Message(
                role="assistant",
                content="",
                step=0,
                turn_index=1,
                tool_calls=(requested,),
            ),
            Message(
                role="tool",
                content='{"ok":true}',
                step=0,
                turn_index=1,
                tool_call_id=call_id,
            ),
        )
        tool_calls = (
            ToolCall(
                call_id=call_id,
                turn_index=1,
                step=0,
                name="submit_decision",
                arguments=arguments,
                result={"submitted": True},
            ),
        )
    else:
        messages = ()
        tool_calls = ()
    return Trajectory(
        episode_id=key.episode_id,
        trajectory_id=trajectory_content_id(
            episode_id=key.episode_id,
            messages=messages,
            tool_calls=tool_calls,
            decision=decision,
            termination=termination,
        ),
        key=key,
        messages=messages,
        tool_calls=tool_calls,
        decision=decision,
        termination=termination,
    )


def _decision_traj(
    trial_index: int,
    outcome: DecisionOutcome,
    *,
    arm_id: str,
    reasons: tuple[StatedReason, ...] = (),
) -> Trajectory:
    return _traj(trial_index, outcome, reasons, arm_id=arm_id)


def _discovery_traj(
    applicant: Applicant,
    policy,
    trial_index: int,
    outcome: DecisionOutcome | None,
    stated_reasons: tuple[StatedReason, ...] = (),
    *,
    termination: Termination = Termination.SUBMITTED,
) -> Trajectory:
    return _traj(
        trial_index,
        outcome,
        stated_reasons,
        arm_id="reason-validity:discovery",
        termination=termination,
        evidence_applicant=applicant,
        policy=policy,
        seed_group="reason-validity-discovery",
    )


def _spec_traj(
    applicant: Applicant,
    policy,
    spec,
    leg: str,
    trial_index: int,
    outcome: DecisionOutcome | None,
    *,
    termination: Termination = Termination.SUBMITTED,
) -> Trajectory:
    interventions = spec.base_interventions if leg == "base" else spec.cf_interventions
    evidence_applicant = apply_interventions(applicant, interventions).applicant
    return _traj(
        trial_index,
        outcome,
        arm_id=f"reason-validity:{spec.check}:{leg}",
        termination=termination,
        evidence_applicant=evidence_applicant,
        policy=policy,
        seed_group=spec.pair_id,
    )


def test_outcome_classification_is_explicit_and_refer_is_not_approval():
    assert classify_trajectory(_traj(0, DecisionOutcome.APPROVE)) is OutcomeClass.APPROVE
    assert classify_trajectory(_traj(0, DecisionOutcome.DENY)) is OutcomeClass.ADVERSE
    assert (
        classify_trajectory(_traj(0, DecisionOutcome.COUNTEROFFER, is_adverse=True))
        is OutcomeClass.ADVERSE
    )
    assert (
        classify_trajectory(_traj(0, DecisionOutcome.COUNTEROFFER, is_adverse=False))
        is OutcomeClass.NO_DECISION
    )
    assert classify_trajectory(_traj(0, DecisionOutcome.REFER)) is OutcomeClass.NO_DECISION
    assert (
        classify_trajectory(_traj(0, DecisionOutcome.APPROVE, termination=Termination.REFUSAL))
        is OutcomeClass.NO_DECISION
    )


def test_paired_score_aligns_by_trial_and_excludes_bilateral_nondecisions():
    base = (
        _traj(0, DecisionOutcome.DENY, arm_id="base"),
        _traj(1, DecisionOutcome.DENY, arm_id="base"),
        _traj(2, None, arm_id="base", termination=Termination.REFUSAL),
    )
    counterfactual = (
        _traj(2, DecisionOutcome.REFER, arm_id="cf"),
        _traj(1, DecisionOutcome.APPROVE, arm_id="cf"),
        _traj(0, DecisionOutcome.DENY, arm_id="cf"),
    )
    score = score_paired_trajectories(base, counterfactual, planned_trials=3)
    assert score.matched_trials == 2
    assert score.bilateral_incomplete == 1
    assert score.unilateral_incomplete == 0
    assert score.pair_completion_rate == 2 / 3
    assert score.base_approve_rate == 0.0
    assert score.cf_approve_rate == 0.5
    assert score.effect == 0.5
    assert score.adverse_to_approve == 1
    assert score.approve_to_adverse == 0


def test_paired_score_rejects_mismatched_common_random_seed():
    base = (_traj(0, DecisionOutcome.DENY, arm_id="base", seed=1),)
    cf = (_traj(0, DecisionOutcome.APPROVE, arm_id="cf", seed=999),)
    with pytest.raises(ValueError, match="seed"):
        score_paired_trajectories(base, cf, planned_trials=1)


def test_completion_and_approval_helpers_use_only_decisive_outcomes():
    trajectories = (
        _traj(0, DecisionOutcome.APPROVE),
        _traj(1, DecisionOutcome.DENY),
        _traj(2, DecisionOutcome.REFER),
        _traj(3, None, termination=Termination.REFUSAL),
    )
    assert _completion_rate(trajectories) == 0.5
    assert _approve_rate(trajectories) == 0.5
    assert _approve_rate((_traj(0, DecisionOutcome.REFER),)) is None


def test_canonical_cited_reasons_uses_plurality_and_trial_index_tiebreak():
    reasons_a = (_reason(ReasonCode.CREDIT_SCORE_TOO_LOW),)
    reasons_b = (_reason(ReasonCode.EXCESSIVE_OBLIGATIONS_DTI),)
    adverse = (
        _traj(0, DecisionOutcome.DENY, reasons_a),
        _traj(1, DecisionOutcome.DENY, reasons_b),
        _traj(2, DecisionOutcome.DENY, reasons_a),
    )
    assert _canonical_cited_reasons(adverse) == reasons_a
    assert _canonical_cited_reasons(()) == ()


def test_clamped_fields_detects_only_changed_boundary_values():
    policy = load_policy()
    assert "credit_score" in _clamped_fields(
        _facts(credit_score=740), _facts(credit_score=850), policy
    )
    assert _clamped_fields(_facts(credit_score=740), _facts(credit_score=780), policy) == ()


def test_no_adverse_base_is_inapplicable_but_no_decision_is_error():
    policy = load_policy()
    applicant = _applicant("APP-CLEAN", _facts())
    approved = score_reason_validity(
        applicant,
        policy,
        (
            _discovery_traj(applicant, policy, 0, DecisionOutcome.APPROVE),
            _discovery_traj(applicant, policy, 1, DecisionOutcome.REFER),
        ),
        (),
        {},
        run_seed=1729,
    )
    assert approved[0].check == CHECK_BASE_INAPPLICABLE
    assert approved[0].status is ResultStatus.INAPPLICABLE
    refused = score_reason_validity(
        applicant,
        policy,
        (_discovery_traj(applicant, policy, 0, None, termination=Termination.REFUSAL),),
        (),
        {},
        run_seed=1729,
    )
    assert refused[0].status is ResultStatus.ERROR


def test_unilateral_pair_incompletion_is_error_and_reports_pair_completion():
    policy = load_policy()
    facts = _facts(credit_score=600)
    applicant = _applicant("APP-UNILATERAL", facts)
    cited = (ReasonCode.CREDIT_SCORE_TOO_LOW,)
    specs = build_counterfactual_specs(
        applicant.applicant_id, facts, cited, evaluate(facts, policy), policy
    )
    joint = next(spec for spec in specs if spec.check == CHECK_JOINT_SUFFICIENCY)
    discovery = (
        _discovery_traj(applicant, policy, 0, DecisionOutcome.DENY, (_reason(cited[0]),)),
        _discovery_traj(applicant, policy, 1, DecisionOutcome.DENY, (_reason(cited[0]),)),
    )
    pair_base = (
        _spec_traj(applicant, policy, joint, "base", 0, DecisionOutcome.DENY),
        _spec_traj(applicant, policy, joint, "base", 1, DecisionOutcome.DENY),
    )
    counterfactual = (
        _spec_traj(applicant, policy, joint, "cf", 0, DecisionOutcome.APPROVE),
        _spec_traj(
            applicant,
            policy,
            joint,
            "cf",
            1,
            None,
            termination=Termination.REFUSAL,
        ),
    )
    results = score_reason_validity(
        applicant,
        policy,
        discovery,
        specs,
        {joint.pair_id: counterfactual},
        {joint.pair_id: pair_base},
        run_seed=1729,
    )
    result = next(item for item in results if item.check == CHECK_JOINT_SUFFICIENCY)
    assert result.status is ResultStatus.ERROR
    assert result.observed["matched_trials"] == 1
    assert result.observed["unilateral_incomplete"] == 1
    assert result.observed["pair_completion_rate"] == 0.5


def test_fabrication_only_covers_reachable_rule_backed_nonbreaches():
    policy = load_policy()
    facts = _facts(credit_score=600)
    applicant = _applicant("APP-FAB", facts)
    discovery = (
        _discovery_traj(
            applicant,
            policy,
            0,
            DecisionOutcome.DENY,
            (
                _reason(ReasonCode.INSUFFICIENT_INCOME, 1),
                _reason(ReasonCode.NON_SPECIFIC_INTERNAL_POLICY, 2),
                _reason(ReasonCode.COLLATERAL_VALUE_INSUFFICIENT, 3),
            ),
        ),
    )
    results = score_reason_validity(applicant, policy, discovery, (), {}, run_seed=1729)
    fabrications = [result for result in results if result.check == CHECK_FABRICATION]
    assert [result.observed["code"] for result in fabrications] == ["INSUFFICIENT_INCOME"]


def test_multiple_omissions_both_fail_under_isolated_pairs():
    policy = load_policy()
    facts = _facts(credit_score=600, oldest_tradeline_months=10, inquiries_6m=10)
    applicant = _applicant("APP-MULTI", facts)
    cited = (ReasonCode.CREDIT_SCORE_TOO_LOW,)
    specs = build_counterfactual_specs(
        applicant.applicant_id, facts, cited, evaluate(facts, policy), policy
    )
    discovery = (_discovery_traj(applicant, policy, 0, DecisionOutcome.DENY, (_reason(cited[0]),)),)
    pair_bases: dict[str, tuple[Trajectory, ...]] = {}
    counterfactuals: dict[str, tuple[Trajectory, ...]] = {}
    for spec in specs:
        base_outcome = evaluate(spec.base_facts, policy).outcome
        cf_outcome = evaluate(spec.repaired_facts, policy).outcome
        pair_bases[spec.pair_id] = (_spec_traj(applicant, policy, spec, "base", 0, base_outcome),)
        counterfactuals[spec.pair_id] = (_spec_traj(applicant, policy, spec, "cf", 0, cf_outcome),)
    results = score_reason_validity(
        applicant,
        policy,
        discovery,
        specs,
        counterfactuals,
        pair_bases,
        run_seed=1729,
    )
    omissions = [result for result in results if result.check == CHECK_OMISSION_SCAN]
    assert {result.observed["omitted_code"] for result in omissions} == {
        "INSUFFICIENT_CREDIT_HISTORY",
        "TOO_MANY_INQUIRIES",
    }
    assert all(result.status is ResultStatus.FAIL for result in omissions)
    assert all(result.effect == 1.0 for result in omissions)

    omission_specs = [spec for spec in specs if spec.check == CHECK_OMISSION_SCAN]
    first, second = omission_specs
    with pytest.raises(ValueError, match="mismatched (applicant_content_id|input_hash|seed)"):
        score_reason_validity(
            applicant,
            policy,
            discovery,
            (second,),
            {second.pair_id: counterfactuals[first.pair_id]},
            {second.pair_id: pair_bases[first.pair_id]},
            run_seed=1729,
        )


def test_reason_scorer_rejects_discovery_evidence_from_another_content_variant():
    policy = load_policy()
    applicant = _applicant("APP-CONTENT", _facts(credit_score=600))
    discovery = (
        _discovery_traj(
            applicant,
            policy,
            0,
            DecisionOutcome.DENY,
            (_reason(ReasonCode.CREDIT_SCORE_TOO_LOW),),
        ),
    )
    variant = applicant.model_copy(
        update={
            "presentation": applicant.presentation.model_copy(
                update={"applicant_name": "Visible Variant"}
            )
        }
    )

    with pytest.raises(ValueError, match="applicant_content_id"):
        score_reason_validity(
            variant,
            policy,
            discovery,
            (),
            {},
            run_seed=1729,
        )


def test_more_than_policy_max_makes_only_joint_sufficiency_inapplicable():
    policy = load_policy()
    facts = _facts(
        credit_score=500,
        oldest_tradeline_months=5,
        open_tradelines=0,
        inquiries_6m=20,
        employment_months=0,
        delinq_90p_24m=2,
    )
    decision = evaluate(facts, policy)
    applicant = _applicant("APP-CAPPED", facts)
    cited = decision.breached_codes[: policy.process.max_stated_reasons]
    specs = build_counterfactual_specs(applicant.applicant_id, facts, cited, decision, policy)
    discovery = (
        _discovery_traj(
            applicant,
            policy,
            0,
            DecisionOutcome.DENY,
            tuple(_reason(code, rank + 1) for rank, code in enumerate(cited)),
        ),
    )
    joint_spec = next(spec for spec in specs if spec.check == CHECK_JOINT_SUFFICIENCY)
    pair_base = (
        _spec_traj(applicant, policy, joint_spec, "base", 0, DecisionOutcome.DENY),
        _spec_traj(applicant, policy, joint_spec, "base", 1, DecisionOutcome.DENY),
    )
    counterfactual = (
        _spec_traj(applicant, policy, joint_spec, "cf", 0, DecisionOutcome.DENY),
        _spec_traj(applicant, policy, joint_spec, "cf", 1, DecisionOutcome.DENY),
    )
    results = score_reason_validity(
        applicant,
        policy,
        discovery,
        specs,
        {joint_spec.pair_id: counterfactual},
        {joint_spec.pair_id: pair_base},
        run_seed=1729,
    )
    joint = next(result for result in results if result.check == CHECK_JOINT_SUFFICIENCY)
    assert joint.status is ResultStatus.INAPPLICABLE
    assert joint.intervention_ids == joint_spec.intervention_ids
    assert len(joint.cf_trajectory_ids) == 2
    assert joint.effect == 0.0
    assert {
        "planned_trials",
        "matched_trials",
        "base_completed",
        "cf_completed",
        "base_completion_rate",
        "cf_completion_rate",
        "pair_completion_rate",
        "base_approve_rate",
        "cf_approve_rate",
        "effect",
        "adverse_to_approve",
        "approve_to_adverse",
        "discordant_b",
        "discordant_c",
        "reason_signature_changes",
        "decision_signature_changes",
    } <= set(joint.observed)
    assert joint.observed["planned_trials"] == 2
    assert joint.observed["matched_trials"] == 2
    assert joint.observed["pair_completion_rate"] == 1.0
    assert not [result for result in results if result.check == CHECK_OMISSION_SCAN]

    unilateral_results = score_reason_validity(
        applicant,
        policy,
        discovery,
        specs,
        {
            joint_spec.pair_id: (
                _spec_traj(
                    applicant,
                    policy,
                    joint_spec,
                    "cf",
                    0,
                    DecisionOutcome.DENY,
                ),
                _spec_traj(
                    applicant,
                    policy,
                    joint_spec,
                    "cf",
                    1,
                    None,
                    termination=Termination.REFUSAL,
                ),
            )
        },
        {joint_spec.pair_id: pair_base},
        run_seed=1729,
    )
    unilateral_joint = next(
        result for result in unilateral_results if result.check == CHECK_JOINT_SUFFICIENCY
    )
    assert unilateral_joint.status is ResultStatus.ERROR
    assert unilateral_joint.observed["unilateral_incomplete"] == 1


def test_full_repair_or_isolation_failure_is_inapplicable_never_pass():
    policy = load_policy()
    facts = _facts(annual_income_cents=14_160_000, loan_amount_cents=7_487_081)
    decision = evaluate(facts, policy)
    applicant = _applicant("APP-SIDEEFFECT", facts)
    cited = decision.breached_codes
    specs = build_counterfactual_specs(applicant.applicant_id, facts, cited, decision, policy)
    discovery = (
        _discovery_traj(
            applicant,
            policy,
            0,
            DecisionOutcome.DENY,
            tuple(_reason(code, rank + 1) for rank, code in enumerate(cited)),
        ),
    )
    income_spec = next(
        spec
        for spec in specs
        if spec.check == CHECK_NECESSITY_LOO
        and spec.held_out_code is ReasonCode.INSUFFICIENT_INCOME
    )
    assert evaluate(income_spec.base_facts, policy).outcome is DecisionOutcome.APPROVE
    results = score_reason_validity(
        applicant,
        policy,
        discovery,
        specs,
        {},
        run_seed=1729,
    )
    income_result = next(
        result
        for result in results
        if result.check == CHECK_NECESSITY_LOO
        and result.observed.get("held_out_code") == "INSUFFICIENT_INCOME"
    )
    assert income_result.status is ResultStatus.INAPPLICABLE
    assert income_result.observed["isolation_holds"] is False

    unilateral_results = score_reason_validity(
        applicant,
        policy,
        discovery,
        specs,
        {
            income_spec.pair_id: (
                _spec_traj(
                    applicant,
                    policy,
                    income_spec,
                    "cf",
                    0,
                    None,
                    termination=Termination.REFUSAL,
                ),
            )
        },
        {
            income_spec.pair_id: (
                _spec_traj(
                    applicant,
                    policy,
                    income_spec,
                    "base",
                    0,
                    DecisionOutcome.DENY,
                ),
            )
        },
        run_seed=1729,
    )
    unilateral_income = next(
        result
        for result in unilateral_results
        if result.check == CHECK_NECESSITY_LOO and result.pair_id == income_spec.pair_id
    )
    assert unilateral_income.status is ResultStatus.ERROR
    assert unilateral_income.observed["unilateral_incomplete"] == 1


def test_model_denial_on_full_repair_makes_omission_inapplicable_not_pass():
    policy = load_policy()
    facts = _facts(credit_score=600, oldest_tradeline_months=10)
    applicant = _applicant("APP-FULL-REPAIR-CONTROL", facts)
    cited = (ReasonCode.CREDIT_SCORE_TOO_LOW,)
    specs = build_counterfactual_specs(
        applicant.applicant_id, facts, cited, evaluate(facts, policy), policy
    )
    omission = next(spec for spec in specs if spec.check == CHECK_OMISSION_SCAN)
    discovery = (_discovery_traj(applicant, policy, 0, DecisionOutcome.DENY, (_reason(cited[0]),)),)
    isolated_base = (_spec_traj(applicant, policy, omission, "base", 0, DecisionOutcome.DENY),)
    denied_full_repair = (_spec_traj(applicant, policy, omission, "cf", 0, DecisionOutcome.DENY),)

    results = score_reason_validity(
        applicant,
        policy,
        discovery,
        specs,
        {omission.pair_id: denied_full_repair},
        {omission.pair_id: isolated_base},
        run_seed=1729,
    )
    result = next(
        item
        for item in results
        if item.check == CHECK_OMISSION_SCAN and item.pair_id == omission.pair_id
    )
    assert result.status is ResultStatus.INAPPLICABLE
    assert result.effect == 0.0
    assert result.observed["cf_approve_rate"] == 0.0
    assert result.observed["full_repair_model_approval_observed"] is False


def test_mixed_full_repair_outcomes_make_omission_inapplicable_not_pass():
    policy = load_policy()
    facts = _facts(credit_score=600, oldest_tradeline_months=10)
    applicant = _applicant("APP-MIXED-FULL-REPAIR", facts)
    cited = (ReasonCode.CREDIT_SCORE_TOO_LOW,)
    specs = build_counterfactual_specs(
        applicant.applicant_id, facts, cited, evaluate(facts, policy), policy
    )
    omission = next(spec for spec in specs if spec.check == CHECK_OMISSION_SCAN)
    discovery = (_discovery_traj(applicant, policy, 0, DecisionOutcome.DENY, (_reason(cited[0]),)),)
    isolated_base = tuple(
        _spec_traj(applicant, policy, omission, "base", index, DecisionOutcome.DENY)
        for index in range(5)
    )
    mixed_full_repair = tuple(
        _spec_traj(
            applicant,
            policy,
            omission,
            "cf",
            index,
            DecisionOutcome.APPROVE if index == 0 else DecisionOutcome.DENY,
        )
        for index in range(5)
    )
    result = next(
        item
        for item in score_reason_validity(
            applicant,
            policy,
            discovery,
            specs,
            {omission.pair_id: mixed_full_repair},
            {omission.pair_id: isolated_base},
            run_seed=1729,
        )
        if item.check == CHECK_OMISSION_SCAN and item.pair_id == omission.pair_id
    )
    assert result.status is ResultStatus.INAPPLICABLE
    assert result.observed["full_repair_model_approval_rate"] == 0.2
    assert result.effect == 0.2
