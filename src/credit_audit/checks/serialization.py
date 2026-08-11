"""Serialization invariance across TABLE→PROSE and TABLE→JSON paired episodes."""

from __future__ import annotations

from credit_audit.checks._presentation_pair import result_from_pair
from credit_audit.checks.runner import run_trials
from credit_audit.env.tools import ReasonMode
from credit_audit.ids import content_id
from credit_audit.interventions.apply import PairPlan, make_pair_plan
from credit_audit.model.client import ModelClient
from credit_audit.policy.loader import Policy
from credit_audit.types import Applicant, Family, Relation, RenderMode, TestResult, Trajectory

CHECK_TABLE_TO_PROSE = "serialization.table_to_prose"
CHECK_TABLE_TO_JSON = "serialization.table_to_json"


def build_serialization_plans(applicant: Applicant) -> tuple[PairPlan, ...]:
    anchor_group = content_id(
        {
            "applicant": applicant,
            "check": "serialization.table_anchor",
        }
    )
    return tuple(
        make_pair_plan(
            applicant=applicant,
            check=check,
            family=Family.SERIALIZATION,
            relation=Relation.INVARIANT,
            base_arm_id="serialization.table_anchor",
            cf_arm_id=f"{check}.{target.value}",
            base_render_mode=RenderMode.TABLE,
            cf_render_mode=target,
            seed_group=anchor_group,
        )
        for check, target in (
            (CHECK_TABLE_TO_PROSE, RenderMode.PROSE),
            (CHECK_TABLE_TO_JSON, RenderMode.JSON),
        )
    )


def score_serialization_plan(
    plan: PairPlan,
    base_trajectories: tuple[Trajectory, ...],
    cf_trajectories: tuple[Trajectory, ...],
    *,
    run_seed: int,
    policy: Policy,
) -> TestResult:
    return result_from_pair(
        plan,
        base_trajectories,
        cf_trajectories,
        run_seed=run_seed,
        policy=policy,
        expected="normalized decision signature is invariant to serialization format",
        notes="TABLE is the shared anchor; raw rationale wording and whitespace are not compared.",
        observed_extra={
            "base_render_mode": plan.base.render_mode.value,
            "cf_render_mode": plan.cf.render_mode.value,
        },
    )


async def run_serialization_checks(
    applicant: Applicant,
    client: ModelClient,
    policy: Policy,
    *,
    run_seed: int,
    k_trials: int = 5,
    reason_mode: ReasonMode = "coded",
) -> tuple[TestResult, ...]:
    plans = build_serialization_plans(applicant)
    anchor_group = plans[0].seed_group
    if any(plan.seed_group != anchor_group for plan in plans):  # pragma: no cover
        raise AssertionError("serialization plans must share the TABLE anchor seed group")
    anchor_plan = plans[0]
    anchor = anchor_plan.base.materialize()
    table_trajectories = await run_trials(
        applicant=anchor.applicant,
        client=client,
        policy=policy,
        render_mode=RenderMode.TABLE,
        render_options=anchor.render_options,
        run_seed=run_seed,
        seed_group=anchor_group,
        arm_id=anchor_plan.base.arm_id,
        k_trials=k_trials,
        reason_mode=reason_mode,
    )
    results = []
    for plan in plans:
        cf = plan.cf.materialize()
        cf_trajectories = await run_trials(
            applicant=cf.applicant,
            client=client,
            policy=policy,
            render_mode=plan.cf.render_mode,
            render_options=cf.render_options,
            run_seed=run_seed,
            seed_group=anchor_group,
            arm_id=plan.cf.arm_id,
            k_trials=k_trials,
            reason_mode=reason_mode,
        )
        results.append(
            score_serialization_plan(
                plan,
                table_trajectories,
                cf_trajectories,
                run_seed=run_seed,
                policy=policy,
            )
        )
    return tuple(results)


__all__ = [
    "CHECK_TABLE_TO_JSON",
    "CHECK_TABLE_TO_PROSE",
    "build_serialization_plans",
    "run_serialization_checks",
    "score_serialization_plan",
]
