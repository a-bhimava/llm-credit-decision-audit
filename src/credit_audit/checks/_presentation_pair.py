"""Shared execution/scoring glue for Phase 6 presentation-surface checks."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from credit_audit.checks.paired import (
    PairedScore,
    score_paired_trajectories,
    validate_pair_plan_trajectories,
)
from credit_audit.checks.runner import run_trials
from credit_audit.env.tools import ReasonMode
from credit_audit.interventions.apply import PairPlan
from credit_audit.model.client import ModelClient
from credit_audit.policy.loader import Policy
from credit_audit.types import FrozenDict, TestResult, TestStatus, Trajectory


async def execute_pair_plan(
    plan: PairPlan,
    *,
    client: ModelClient,
    policy: Policy,
    run_seed: int,
    k_trials: int,
    reason_mode: ReasonMode = "coded",
) -> tuple[tuple[Trajectory, ...], tuple[Trajectory, ...]]:
    base = plan.base.materialize()
    cf = plan.cf.materialize()
    base_trajectories = await run_trials(
        applicant=base.applicant,
        client=client,
        policy=policy,
        render_mode=plan.base.render_mode,
        render_options=base.render_options,
        run_seed=run_seed,
        seed_group=plan.seed_group,
        arm_id=plan.base.arm_id,
        k_trials=k_trials,
        reason_mode=reason_mode,
        interventions=plan.base.interventions,
    )
    cf_trajectories = await run_trials(
        applicant=cf.applicant,
        client=client,
        policy=policy,
        render_mode=plan.cf.render_mode,
        render_options=cf.render_options,
        run_seed=run_seed,
        seed_group=plan.seed_group,
        arm_id=plan.cf.arm_id,
        k_trials=k_trials,
        reason_mode=reason_mode,
        interventions=plan.cf.interventions,
    )
    return base_trajectories, cf_trajectories


def result_from_pair(
    plan: PairPlan,
    base_trajectories: tuple[Trajectory, ...],
    cf_trajectories: tuple[Trajectory, ...],
    *,
    run_seed: int,
    policy: Policy,
    expected: str,
    notes: str,
    observed_extra: Mapping[str, Any] | None = None,
) -> TestResult:
    validate_pair_plan_trajectories(
        plan,
        base_trajectories,
        cf_trajectories,
        run_seed=run_seed,
        policy=policy,
    )
    score = score_paired_trajectories(
        base_trajectories,
        cf_trajectories,
        planned_trials=max(len(base_trajectories), len(cf_trajectories)),
    )
    holds = score.relation_holds(plan.relation)
    status = TestStatus.ERROR if holds is None else TestStatus.PASS if holds else TestStatus.FAIL
    observed = dict(score.observed())
    observed["seed_group"] = plan.seed_group
    observed.update(observed_extra or {})
    return TestResult(
        test_id=plan.pair_id,
        check=plan.check,
        family=plan.family,
        applicant_id=plan.base.applicant.applicant_id,
        intervention_ids=(
            *plan.base.intervention_ids,
            *plan.cf.intervention_ids,
        ),
        base_trajectory_ids=tuple(t.trajectory_id for t in base_trajectories),
        cf_trajectory_ids=tuple(t.trajectory_id for t in cf_trajectories),
        status=status,
        observed=FrozenDict(observed),
        expected=expected,
        effect=score.effect,
        pair_id=plan.pair_id,
        cluster_id=plan.cluster_id,
        notes=notes,
    )


def score_pair(
    base_trajectories: tuple[Trajectory, ...],
    cf_trajectories: tuple[Trajectory, ...],
) -> PairedScore:
    """Small public alias used by tests that want metrics without a TestResult."""

    return score_paired_trajectories(
        base_trajectories,
        cf_trajectories,
        planned_trials=max(len(base_trajectories), len(cf_trajectories)),
    )


__all__ = ["execute_pair_plan", "result_from_pair", "score_pair"]
