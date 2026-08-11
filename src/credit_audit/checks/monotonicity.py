"""Phase-6 policy-boundary monotonicity checks."""

from __future__ import annotations

from credit_audit.checks.paired import (
    PairedScore,
    score_paired_trajectories,
    validate_pair_plan_trajectories,
)
from credit_audit.checks.runner import run_arm_trials
from credit_audit.env.tools import ReasonMode
from credit_audit.interventions.apply import make_pair_plan
from credit_audit.interventions.monotone import (
    MonotonicityCase,
    build_analytic_income_case,
    build_monotonicity_cases,
)
from credit_audit.model.client import ModelClient
from credit_audit.policy.loader import Policy
from credit_audit.types import (
    Applicant,
    Family,
    FrozenDict,
    Relation,
    RenderMode,
    TestResult,
    TestStatus,
    Trajectory,
)


def _empty_metrics(reason: str, *, planned_trials: int) -> FrozenDict:
    return FrozenDict(
        {
            "planned_trials": planned_trials,
            "matched_trials": 0,
            "base_completed": 0,
            "cf_completed": 0,
            "base_completion_rate": 0.0,
            "cf_completion_rate": 0.0,
            "bilateral_incomplete": 0,
            "unilateral_incomplete": 0,
            "pair_completion_rate": 0.0,
            "base_approve_rate": None,
            "cf_approve_rate": None,
            "effect": None,
            "adverse_to_approve": 0,
            "approve_to_adverse": 0,
            "discordant_b": 0,
            "discordant_c": 0,
            "reason_signature_changes": 0,
            "decision_signature_changes": 0,
            "violation_count": 0,
            "violation_rate": None,
            "construction_error": reason,
        }
    )


def _violations(score: PairedScore, relation: Relation) -> tuple[int, float | None]:
    if relation is Relation.NONDECREASING:
        count = score.approve_to_adverse
    elif relation is Relation.NONINCREASING:
        count = score.adverse_to_approve
    else:  # pragma: no cover - plans in this module are monotone by construction
        raise ValueError(f"unsupported monotonicity relation: {relation}")
    return count, count / score.matched_trials if score.matched_trials else None


def score_monotonicity_case(
    case: MonotonicityCase,
    base_trajectories: tuple[Trajectory, ...] = (),
    cf_trajectories: tuple[Trajectory, ...] = (),
    *,
    planned_trials: int | None = None,
    run_seed: int | None = None,
    policy: Policy | None = None,
) -> TestResult:
    """Score one monotonicity case using matched trial indices only."""

    if case.plan is None:
        return TestResult(
            test_id=case.pair_id,
            check=case.check,
            family=Family.MONOTONE,
            applicant_id=case.applicant_id,
            status=TestStatus.INAPPLICABLE,
            observed=_empty_metrics(
                case.inapplicable_reason or "construction unavailable",
                planned_trials=planned_trials or 0,
            ),
            expected=case.expected_relation.value,
            pair_id=case.pair_id,
            cluster_id=case.cluster_id,
            notes=case.inapplicable_reason or "",
        )

    if run_seed is None or policy is None:
        raise ValueError("run_seed and policy are required when scoring an applicable PairPlan")
    validate_pair_plan_trajectories(
        case.plan,
        base_trajectories,
        cf_trajectories,
        run_seed=run_seed,
        policy=policy,
    )
    score = score_paired_trajectories(
        base_trajectories,
        cf_trajectories,
        planned_trials=planned_trials,
    )
    holds = score.relation_holds(case.expected_relation)
    violation_count, violation_rate = _violations(score, case.expected_relation)
    if score.has_unilateral_incomplete:
        status = TestStatus.ERROR
    elif holds is None:
        status = TestStatus.INAPPLICABLE
    else:
        # A rate difference can hide paired reversals when violations and improvements
        # cancel (b == c).  Monotonicity is a per-pair metamorphic relation, so any
        # forbidden matched transition is a raw Phase-6 failure; Phase 7 owns inference
        # over the disclosed violation rate.
        status = TestStatus.FAIL if violation_count else TestStatus.PASS
    observed = dict(score.observed())
    observed.update(
        {
            "target_rule_id": case.target_rule_id,
            "seed_group": case.plan.seed_group,
            "violation_count": violation_count,
            "violation_rate": violation_rate,
        }
    )
    return TestResult(
        test_id=case.pair_id,
        check=case.check,
        family=Family.MONOTONE,
        applicant_id=case.plan.base.applicant.applicant_id,
        intervention_ids=(
            *case.plan.base.intervention_ids,
            *case.plan.cf.intervention_ids,
        ),
        base_trajectory_ids=tuple(t.trajectory_id for t in base_trajectories),
        cf_trajectory_ids=tuple(t.trajectory_id for t in cf_trajectories),
        status=status,
        observed=FrozenDict(observed),
        expected=case.expected_relation.value,
        effect=score.effect,
        pair_id=case.pair_id,
        cluster_id=case.cluster_id,
    )


async def run_monotonicity_check(
    applicant: Applicant,
    client: ModelClient,
    policy: Policy,
    run_seed: int,
    *,
    render_mode: RenderMode = RenderMode.TABLE,
    k_trials: int = 5,
    reason_mode: ReasonMode = "coded",
    include_analytic_income_fixture: bool = False,
) -> tuple[TestResult, ...]:
    """Construct, execute, and score all applicable monotonicity pairs."""

    cases = list(build_monotonicity_cases(applicant, policy))
    if include_analytic_income_fixture:
        cases.append(build_analytic_income_case(applicant, policy))

    results: list[TestResult] = []
    for case in cases:
        if case.plan is None:
            results.append(score_monotonicity_case(case, planned_trials=k_trials))
            continue
        # Rebuild the canonical contrast identity when the caller changes renderer; a
        # PairPlan's hash covers its full arm specs and render modes.
        active_plan = make_pair_plan(
            applicant=case.plan.base.applicant,
            check=case.check,
            family=case.plan.family,
            relation=case.plan.relation,
            base_arm_id=case.plan.base.arm_id,
            cf_arm_id=case.plan.cf.arm_id,
            base_render_mode=render_mode,
            cf_render_mode=render_mode,
            base_interventions=case.plan.base.interventions,
            cf_interventions=case.plan.cf.interventions,
        )
        active_case = case.model_copy(
            update={
                "pair_id": active_plan.pair_id,
                "cluster_id": active_plan.cluster_id,
                "plan": active_plan,
            }
        )
        base = await run_arm_trials(
            arm=active_plan.base,
            client=client,
            policy=policy,
            run_seed=run_seed,
            seed_group=active_plan.seed_group,
            k_trials=k_trials,
            reason_mode=reason_mode,
        )
        cf = await run_arm_trials(
            arm=active_plan.cf,
            client=client,
            policy=policy,
            run_seed=run_seed,
            seed_group=active_plan.seed_group,
            k_trials=k_trials,
            reason_mode=reason_mode,
        )
        results.append(
            score_monotonicity_case(
                active_case,
                base,
                cf,
                planned_trials=k_trials,
                run_seed=run_seed,
                policy=policy,
            )
        )
    return tuple(results)


__all__ = [
    "run_monotonicity_check",
    "score_monotonicity_case",
]
