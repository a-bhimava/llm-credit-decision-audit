from __future__ import annotations

import asyncio

import pytest

from credit_audit.checks.monotonicity import (
    run_monotonicity_check,
    score_monotonicity_case,
)
from credit_audit.checks.runner import run_arm_trials
from credit_audit.ids import (
    applicant_content_id,
    content_id,
    episode_input_hash,
    trajectory_content_id,
)
from credit_audit.interventions.monotone import (
    CHECK_INCOME_ANALYTIC,
    CHECK_MAJOR_DELINQUENCY,
    build_analytic_income_case,
    build_monotonicity_cases,
)
from credit_audit.model.scripted import FaithfulAgent, NonMonotoneAgent
from credit_audit.render.reference import applicant_reference_for
from credit_audit.render.registry import render_application
from credit_audit.types import (
    Decision,
    DecisionOutcome,
    EpisodeKey,
    Message,
    RequestedToolCall,
    Termination,
    ToolCall,
    Trajectory,
)
from credit_audit.types import TestStatus as AuditStatus


def _trajectory(
    case,
    policy,
    trial_index: int,
    leg: str,
    outcome: DecisionOutcome,
    *,
    arm_id_override: str | None = None,
) -> Trajectory:
    assert case.plan is not None
    arm = case.plan.base if leg == "base" else case.plan.cf
    materialized = arm.materialize()
    applicant = materialized.applicant
    application_text = render_application(
        applicant,
        arm.render_mode,
        policy,
        options=materialized.render_options,
    )
    key = EpisodeKey(
        applicant_id=case.applicant_id,
        applicant_content_id=applicant_content_id(applicant),
        arm_id=arm_id_override or arm.arm_id,
        render_id=arm.render_mode,
        trial_index=trial_index,
        model_id="unit:paired",
        prompt_hash="unit-only",
        input_hash=episode_input_hash(
            applicant,
            application_text=application_text,
            applicant_ref=applicant_reference_for(applicant),
            render_mode=arm.render_mode,
        ),
        seed=case.plan.trial_seed(1729, trial_index),
    )
    decision = Decision(
        outcome=outcome,
        is_adverse_action=outcome is DecisionOutcome.DENY,
    )
    call_id = f"submit-{trial_index}"
    arguments = {"outcome": outcome.value}
    messages = (
        Message(
            role="assistant",
            content="",
            step=0,
            turn_index=1,
            tool_calls=(
                RequestedToolCall(
                    call_id=call_id,
                    name="submit_decision",
                    arguments=arguments,
                ),
            ),
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
    return Trajectory(
        episode_id=key.episode_id,
        trajectory_id=trajectory_content_id(
            episode_id=key.episode_id,
            messages=messages,
            tool_calls=tool_calls,
            decision=decision,
            termination=Termination.SUBMITTED,
        ),
        key=key,
        messages=messages,
        tool_calls=tool_calls,
        decision=decision,
        termination=Termination.SUBMITTED,
    )


def test_boundary_cases_are_absolute_isolated_and_preserve_presentation(
    golden_clean_applicant, policy
):
    presentation_hash = content_id(golden_clean_applicant.presentation)
    cases = build_monotonicity_cases(golden_clean_applicant, policy)
    assert len(cases) == 5
    assert all(case.plan is not None for case in cases)

    for case in cases:
        assert case.plan is not None
        base = case.plan.base.materialize().applicant
        cf = case.plan.cf.materialize().applicant
        assert base.applicant_id == cf.applicant_id == golden_clean_applicant.applicant_id
        assert content_id(base.presentation) == presentation_hash
        assert content_id(cf.presentation) == presentation_hash

    major = next(case for case in cases if case.check == CHECK_MAJOR_DELINQUENCY)
    assert major.plan is not None
    major_rule = policy.rule("max_major_delinquencies")
    assert major.plan.base.interventions[0].params["targets"]["delinq_90p_24m"] == int(
        major_rule.threshold
    )
    assert major.plan.cf.interventions[0].params["targets"]["delinq_90p_24m"] == int(
        major_rule.threshold + major_rule.margin_unit
    )


def test_non_clean_source_is_inapplicable(multi_breach_applicant, policy):
    cases = build_monotonicity_cases(multi_breach_applicant, policy)
    assert all(case.plan is None for case in cases)
    assert all(
        case.inapplicable_reason == "source profile is not oracle-approved" for case in cases
    )


def test_faithful_agent_passes_every_boundary_monotonicity_case(golden_clean_applicant, policy):
    results = asyncio.run(
        run_monotonicity_check(
            golden_clean_applicant,
            FaithfulAgent(),
            policy,
            1729,
            k_trials=1,
        )
    )
    assert len(results) == 5
    assert all(result.status is AuditStatus.PASS for result in results)
    required_metrics = {
        "planned_trials",
        "matched_trials",
        "base_completed",
        "cf_completed",
        "base_completion_rate",
        "cf_completion_rate",
        "bilateral_incomplete",
        "unilateral_incomplete",
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
        "violation_count",
        "violation_rate",
    }
    assert all(required_metrics <= set(result.observed) for result in results)


def test_non_monotone_agent_violates_exact_30k_to_40k_fixture_at_100_percent(
    golden_clean_applicant, policy
):
    case = build_analytic_income_case(golden_clean_applicant, policy)
    assert case.check == CHECK_INCOME_ANALYTIC
    assert case.plan is not None

    async def execute():
        base = await run_arm_trials(
            arm=case.plan.base,
            client=NonMonotoneAgent(),
            policy=policy,
            run_seed=1729,
            seed_group=case.plan.seed_group,
            k_trials=3,
        )
        cf = await run_arm_trials(
            arm=case.plan.cf,
            client=NonMonotoneAgent(),
            policy=policy,
            run_seed=1729,
            seed_group=case.plan.seed_group,
            k_trials=3,
        )
        return base, cf

    base, cf = asyncio.run(execute())
    assert (
        [t.key.seed for t in base]
        == [t.key.seed for t in cf]
        == [case.plan.trial_seed(1729, index) for index in range(3)]
    )
    assert all(base_t.episode_id != cf_t.episode_id for base_t, cf_t in zip(base, cf, strict=True))
    result = score_monotonicity_case(
        case,
        base,
        cf,
        planned_trials=3,
        run_seed=1729,
        policy=policy,
    )
    assert result.status is AuditStatus.FAIL
    assert result.effect == -1.0
    assert result.observed["approve_to_adverse"] == 3
    assert result.observed["violation_rate"] == 1.0


def test_opposite_discordances_do_not_cancel_a_monotonicity_violation(
    golden_clean_applicant, policy
):
    case = build_analytic_income_case(golden_clean_applicant, policy)
    base = (
        _trajectory(case, policy, 0, "base", DecisionOutcome.APPROVE),
        _trajectory(case, policy, 1, "base", DecisionOutcome.DENY),
    )
    cf = (
        _trajectory(case, policy, 0, "cf", DecisionOutcome.DENY),
        _trajectory(case, policy, 1, "cf", DecisionOutcome.APPROVE),
    )
    result = score_monotonicity_case(
        case,
        base,
        cf,
        planned_trials=2,
        run_seed=1729,
        policy=policy,
    )
    assert result.effect == 0.0
    assert result.observed["approve_to_adverse"] == 1
    assert result.observed["adverse_to_approve"] == 1
    assert result.observed["violation_count"] == 1
    assert result.status is AuditStatus.FAIL


def test_plan_scorer_rejects_trajectories_from_a_different_arm(golden_clean_applicant, policy):
    case = build_analytic_income_case(golden_clean_applicant, policy)
    base = (
        _trajectory(
            case,
            policy,
            0,
            "base",
            DecisionOutcome.APPROVE,
            arm_id_override="unrelated-arm",
        ),
    )
    cf = (_trajectory(case, policy, 0, "cf", DecisionOutcome.APPROVE),)

    with pytest.raises(ValueError, match="PairPlan base.*mismatched arm_id"):
        score_monotonicity_case(
            case,
            base,
            cf,
            planned_trials=1,
            run_seed=1729,
            policy=policy,
        )


def test_inapplicable_cases_still_export_the_complete_paired_metric_shape(
    multi_breach_applicant, policy
):
    required_metrics = {
        "planned_trials",
        "matched_trials",
        "base_completed",
        "cf_completed",
        "base_completion_rate",
        "cf_completion_rate",
        "bilateral_incomplete",
        "unilateral_incomplete",
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
        "violation_count",
        "violation_rate",
    }
    for case in build_monotonicity_cases(multi_breach_applicant, policy):
        result = score_monotonicity_case(case, planned_trials=5)
        assert result.status is AuditStatus.INAPPLICABLE
        assert result.observed["planned_trials"] == 5
        assert required_metrics <= set(result.observed)


def test_inapplicable_pair_ids_include_source_content(multi_breach_applicant, policy):
    variant = multi_breach_applicant.model_copy(
        update={"facts": multi_breach_applicant.facts.model_copy(update={"loan_term_months": 36})}
    )
    original_ids = {
        case.pair_id for case in build_monotonicity_cases(multi_breach_applicant, policy)
    }
    variant_ids = {case.pair_id for case in build_monotonicity_cases(variant, policy)}
    assert original_ids.isdisjoint(variant_ids)
