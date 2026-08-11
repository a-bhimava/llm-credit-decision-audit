"""Presentation invariance checks: statement order, JSON field order, and paraphrase."""

from __future__ import annotations

from credit_audit.checks._presentation_pair import execute_pair_plan, result_from_pair
from credit_audit.env.tools import ReasonMode
from credit_audit.interventions.apply import PairPlan, make_pair_plan
from credit_audit.interventions.presentation import (
    PresentationContrast,
    field_order_contrast,
    paraphrase_contrast,
    statement_order_contrast,
)
from credit_audit.model.client import ModelClient
from credit_audit.policy.loader import Policy
from credit_audit.types import Applicant, Family, Relation, RenderMode, TestResult, Trajectory

CHECK_STATEMENT_ORDER = "invariance.statement_order"
CHECK_FIELD_ORDER = "invariance.field_order"
CHECK_PARAPHRASE = "invariance.paraphrase"


def _plan(
    applicant: Applicant,
    contrast: PresentationContrast,
    *,
    check: str,
    render_mode: RenderMode,
) -> PairPlan:
    return make_pair_plan(
        applicant=applicant,
        check=check,
        family=Family.INVARIANCE,
        relation=Relation.INVARIANT,
        base_arm_id=f"{check}.base",
        cf_arm_id=f"{check}.cf",
        base_render_mode=render_mode,
        cf_render_mode=render_mode,
        base_interventions=(contrast.base_spec,),
        cf_interventions=(contrast.cf_spec,),
    )


def build_invariance_plans(applicant: Applicant) -> tuple[PairPlan, ...]:
    return (
        _plan(
            applicant,
            statement_order_contrast(),
            check=CHECK_STATEMENT_ORDER,
            render_mode=RenderMode.TABLE,
        ),
        _plan(
            applicant,
            field_order_contrast(),
            check=CHECK_FIELD_ORDER,
            render_mode=RenderMode.JSON,
        ),
        _plan(
            applicant,
            paraphrase_contrast(),
            check=CHECK_PARAPHRASE,
            render_mode=RenderMode.TABLE,
        ),
    )


def score_invariance_plan(
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
        expected="normalized decision signature is identical across the surface-only change",
        notes="Surface invariance compares outcome, terms, risk grade, and ordered reason codes.",
    )


async def run_invariance_checks(
    applicant: Applicant,
    client: ModelClient,
    policy: Policy,
    *,
    run_seed: int,
    k_trials: int = 5,
    reason_mode: ReasonMode = "coded",
) -> tuple[TestResult, ...]:
    results = []
    for plan in build_invariance_plans(applicant):
        base, cf = await execute_pair_plan(
            plan,
            client=client,
            policy=policy,
            run_seed=run_seed,
            k_trials=k_trials,
            reason_mode=reason_mode,
        )
        results.append(
            score_invariance_plan(
                plan,
                base,
                cf,
                run_seed=run_seed,
                policy=policy,
            )
        )
    return tuple(results)


__all__ = [
    "CHECK_FIELD_ORDER",
    "CHECK_PARAPHRASE",
    "CHECK_STATEMENT_ORDER",
    "build_invariance_plans",
    "run_invariance_checks",
    "score_invariance_plan",
]
