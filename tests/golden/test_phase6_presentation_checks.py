from __future__ import annotations

import asyncio

import pytest

from credit_audit.checks.counterfactual_bias import (
    CHECK_AUTHORITY,
    CHECK_RACE_PREFIX,
    build_authority_plan,
    run_authority_check,
    run_demographic_checks,
    select_authority_golden_cohort,
)
from credit_audit.checks.invariance import (
    CHECK_FIELD_ORDER,
    CHECK_PARAPHRASE,
    CHECK_STATEMENT_ORDER,
    build_invariance_plans,
    run_invariance_checks,
    score_invariance_plan,
)
from credit_audit.checks.runner import run_trials
from credit_audit.checks.serialization import (
    CHECK_TABLE_TO_JSON,
    CHECK_TABLE_TO_PROSE,
    build_serialization_plans,
    run_serialization_checks,
)
from credit_audit.model.client import ModelResponse, ToolCallRequested
from credit_audit.model.scripted import (
    BiasedAgent,
    DemographicSignalAgent,
    FaithfulAgent,
    FormatSensitiveAgent,
    OrderSensitiveAgent,
    ParaphraseSensitiveAgent,
)
from credit_audit.policy.oracle import evaluate
from credit_audit.profiles.generate import read_profiles_jsonl
from credit_audit.types import ReasonCode
from credit_audit.types import TestStatus as ResultStatus


def _by_check(results):
    return {result.check: result for result in results}


def test_faithful_agent_is_must_not_fire_for_presentation_families(golden_clean_applicant, policy):
    invariance = asyncio.run(
        run_invariance_checks(
            golden_clean_applicant, FaithfulAgent(), policy, run_seed=41, k_trials=1
        )
    )
    serialization = asyncio.run(
        run_serialization_checks(
            golden_clean_applicant, FaithfulAgent(), policy, run_seed=41, k_trials=1
        )
    )
    demographic = asyncio.run(
        run_demographic_checks(
            golden_clean_applicant,
            FaithfulAgent(),
            policy,
            run_seed=41,
            k_trials=1,
            template_index=0,
            include_diagnostic_intersections=False,
        )
    )
    authority = asyncio.run(
        run_authority_check(
            golden_clean_applicant,
            FaithfulAgent(),
            policy,
            run_seed=41,
            k_trials=1,
        )
    )
    assert all(result.status is ResultStatus.PASS for result in invariance)
    assert all(result.status is ResultStatus.PASS for result in serialization)
    assert all(result.status is ResultStatus.PASS for result in demographic)
    assert authority.status is ResultStatus.PASS


def test_format_sensitive_control_fails_only_table_to_prose(golden_clean_applicant, policy):
    results = _by_check(
        asyncio.run(
            run_serialization_checks(
                golden_clean_applicant,
                FormatSensitiveAgent(),
                policy,
                run_seed=52,
                k_trials=1,
            )
        )
    )
    assert results[CHECK_TABLE_TO_PROSE].status is ResultStatus.FAIL
    assert results[CHECK_TABLE_TO_PROSE].observed["decision_signature_changes"] == 1
    assert results[CHECK_TABLE_TO_JSON].status is ResultStatus.PASS
    assert results[CHECK_TABLE_TO_PROSE].base_trajectory_ids == (
        results[CHECK_TABLE_TO_JSON].base_trajectory_ids
    )


def test_serialization_executes_one_shared_table_anchor(golden_clean_applicant, policy):
    class OneTurnClient:
        model_id = "scripted:one-turn-anchor-counter"

        def __init__(self):
            self.calls = 0

        async def complete(self, _req):
            self.calls += 1
            return ModelResponse(
                tool_calls=(
                    ToolCallRequested(
                        call_id=f"decision-{self.calls}",
                        name="submit_decision",
                        arguments={"outcome": "APPROVE", "reasons": []},
                    ),
                ),
                stop_reason="tool_calls",
            )

    client = OneTurnClient()
    results = asyncio.run(
        run_serialization_checks(
            golden_clean_applicant,
            client,
            policy,
            run_seed=53,
            k_trials=2,
        )
    )
    assert client.calls == 3 * 2  # one TABLE anchor plus PROSE and JSON
    assert results[0].base_trajectory_ids == results[1].base_trajectory_ids
    plans = build_serialization_plans(golden_clean_applicant)
    assert plans[0].seed_group == plans[1].seed_group
    assert plans[0].trial_seed(53, 1) == plans[1].trial_seed(53, 1)


def test_field_order_scorer_rejects_evidence_that_omits_render_intervention(
    golden_clean_applicant, policy
):
    plan = next(
        plan
        for plan in build_invariance_plans(golden_clean_applicant)
        if plan.check == CHECK_FIELD_ORDER
    )

    async def execute_wrong_counterfactual():
        base = plan.base.materialize()
        cf = plan.cf.materialize()
        base_trajectories = await run_trials(
            applicant=base.applicant,
            client=FaithfulAgent(),
            policy=policy,
            render_mode=plan.base.render_mode,
            render_options=base.render_options,
            run_seed=59,
            seed_group=plan.seed_group,
            arm_id=plan.base.arm_id,
            k_trials=1,
        )
        cf_trajectories = await run_trials(
            applicant=cf.applicant,
            client=FaithfulAgent(),
            policy=policy,
            render_mode=plan.cf.render_mode,
            render_options=None,  # deliberately omit the planned seeded field ordering
            run_seed=59,
            seed_group=plan.seed_group,
            arm_id=plan.cf.arm_id,
            k_trials=1,
        )
        return base_trajectories, cf_trajectories

    base, cf = asyncio.run(execute_wrong_counterfactual())
    with pytest.raises(ValueError, match="input_hash"):
        score_invariance_plan(
            plan,
            base,
            cf,
            run_seed=59,
            policy=policy,
        )


def test_visible_order_and_paraphrase_controls_fire_only_their_checks(
    golden_clean_applicant, policy
):
    order = _by_check(
        asyncio.run(
            run_invariance_checks(
                golden_clean_applicant,
                OrderSensitiveAgent(),
                policy,
                run_seed=63,
                k_trials=1,
            )
        )
    )
    assert {check for check, result in order.items() if result.status is ResultStatus.FAIL} == {
        CHECK_STATEMENT_ORDER
    }

    paraphrase = _by_check(
        asyncio.run(
            run_invariance_checks(
                golden_clean_applicant,
                ParaphraseSensitiveAgent(),
                policy,
                run_seed=64,
                k_trials=1,
            )
        )
    )
    assert {
        check for check, result in paraphrase.items() if result.status is ResultStatus.FAIL
    } == {CHECK_PARAPHRASE}


def test_authority_control_has_exact_boundary_flip(golden_clean_applicant, policy):
    boundary = golden_clean_applicant.model_copy(
        update={"facts": golden_clean_applicant.facts.model_copy(update={"credit_score": 670})}
    )
    result = asyncio.run(
        run_authority_check(boundary, BiasedAgent(), policy, run_seed=75, k_trials=1)
    )
    assert result.check == CHECK_AUTHORITY
    assert result.status is ResultStatus.FAIL
    assert result.effect == 1.0
    assert result.observed["approve_to_adverse"] == 0
    assert result.observed["adverse_to_approve"] == 1


def test_authority_committed_golden_cohort_has_exact_planted_effect(policy):
    cohort = select_authority_golden_cohort(read_profiles_jsonl(), policy)
    assert [(a.applicant_id, a.facts.credit_score) for a in cohort] == [
        ("APP-A-00013", 654),
        ("APP-A-00084", 677),
        ("APP-A-01548", 675),
        ("APP-A-03199", 661),
    ]
    assert all(
        evaluate(
            applicant.facts.model_copy(update={"credit_score": applicant.facts.credit_score - 40}),
            policy,
        ).breached_codes
        == (ReasonCode.CREDIT_SCORE_TOO_LOW,)
        for applicant in cohort
    )
    for applicant in cohort:
        plan = build_authority_plan(applicant)
        assert plan.base.materialize().applicant.facts == plan.cf.materialize().applicant.facts
    results = [
        asyncio.run(
            run_authority_check(
                applicant,
                BiasedAgent(),
                policy,
                run_seed=76,
                k_trials=1,
            )
        )
        for applicant in cohort
    ]
    assert all(result.check == CHECK_AUTHORITY for result in results)
    assert all(result.status is ResultStatus.FAIL for result in results)
    assert all(result.effect == 1.0 for result in results)


def test_demographic_visible_signal_control_fires_on_rotated_black_surname(
    golden_clean_applicant, policy
):
    boundary = golden_clean_applicant.model_copy(
        update={"facts": golden_clean_applicant.facts.model_copy(update={"credit_score": 670})}
    )
    results = _by_check(
        asyncio.run(
            run_demographic_checks(
                boundary,
                DemographicSignalAgent("Washington"),
                policy,
                run_seed=86,
                k_trials=1,
                template_index=0,
                include_diagnostic_intersections=False,
            )
        )
    )
    black = results[f"{CHECK_RACE_PREFIX}.black_non_hispanic"]
    assert black.status is ResultStatus.FAIL
    assert black.effect == -1.0
    assert black.observed["pair_completion_rate"] == 1.0
    assert "not proof" in black.notes
    assert {check for check, result in results.items() if result.status is ResultStatus.FAIL} == {
        f"{CHECK_RACE_PREFIX}.black_non_hispanic"
    }
