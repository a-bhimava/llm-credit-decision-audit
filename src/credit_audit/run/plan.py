"""Dry-run planning: what a run will execute, before it executes anything.

Every family except reason repair builds its contrasts from the applicant and the policy
alone, with no model in the loop, so its episode count is known exactly before the first
call. Reason repair is different by construction: which pairs exist depends on which reasons
the agent actually cited, which is not knowable until the discovery trials have run.

The planner reports that honestly rather than inventing a single number. Static families get
an exact count; reason repair gets a lower bound (discovery only) and an upper bound derived
from the policy's reason cap and the applicant's oracle breaches. The budget admits a run
against the **upper** bound, so a plan that might overrun is refused up front instead of
aborting halfway with a partial bundle.
"""

from __future__ import annotations

from credit_audit.checks.counterfactual_bias import build_demographic_plans
from credit_audit.checks.invariance import build_invariance_plans
from credit_audit.checks.serialization import build_serialization_plans
from credit_audit.interventions.monotone import (
    build_analytic_income_case,
    build_monotonicity_cases,
)
from credit_audit.policy.loader import Policy
from credit_audit.policy.oracle import evaluate
from credit_audit.suites.loader import Family, Suite
from credit_audit.types import Applicant, DecisionOutcome, Frozen


class FamilyPlan(Frozen):
    family: Family
    n_applicants: int
    episodes_min: int
    episodes_max: int
    exact: bool
    note: str = ""

    @property
    def uncertain(self) -> bool:
        return not self.exact


class RunPlan(Frozen):
    suite: str
    n_applicants: int
    k_trials: int
    families: tuple[FamilyPlan, ...]

    @property
    def episodes_min(self) -> int:
        return sum(family.episodes_min for family in self.families)

    @property
    def episodes_max(self) -> int:
        return sum(family.episodes_max for family in self.families)

    @property
    def exact(self) -> bool:
        return all(family.exact for family in self.families)


def _monotonicity_episodes(applicant: Applicant, policy: Policy, k: int) -> int:
    cases = [
        *build_monotonicity_cases(applicant, policy),
        build_analytic_income_case(applicant, policy),
    ]
    # An inapplicable case is scored without executing anything: isolation was impossible, so
    # there is no pair to run.
    return sum(2 * k for case in cases if case.plan is not None)


def _reason_validity_bounds(applicant: Applicant, policy: Policy, k: int) -> tuple[int, int]:
    """Discovery is certain; the pairs it implies are not.

    Upper bound: joint sufficiency is one pair, and every code that could be cited or is
    genuinely breached can contribute at most one isolation pair. Bounding by the policy's
    reason cap plus the oracle's breach count is generous on purpose -- a bound that
    occasionally overestimates costs a rejected run, while one that underestimates costs an
    overrun, and only one of those is recoverable.
    """

    discovery = k
    decision = evaluate(applicant.facts, policy)
    if decision.outcome is DecisionOutcome.APPROVE:
        # An approved base cannot support an adverse-action contrast; the check reports
        # `reason_validity.base_inapplicable` after discovery and stops.
        return discovery, discovery
    n_breached = len(set(decision.breached_codes))
    max_pairs = 1 + policy.process.max_stated_reasons + n_breached
    return discovery, discovery + max_pairs * 2 * k


def plan_family(
    family: Family,
    applicants: tuple[Applicant, ...],
    policy: Policy,
    *,
    k_trials: int,
) -> FamilyPlan:
    n = len(applicants)
    if family is Family.POLICY_ADHERENCE:
        episodes = n * k_trials
        return FamilyPlan(
            family=family,
            n_applicants=n,
            episodes_min=episodes,
            episodes_max=episodes,
            exact=True,
            note="one single-arm trial set per applicant",
        )

    if family is Family.MONOTONICITY:
        episodes = sum(_monotonicity_episodes(a, policy, k_trials) for a in applicants)
        return FamilyPlan(
            family=family,
            n_applicants=n,
            episodes_min=episodes,
            episodes_max=episodes,
            exact=True,
            note="applicable boundary-straddling cases only",
        )

    if family is Family.INVARIANCE:
        episodes = sum(2 * k_trials * len(build_invariance_plans(a)) for a in applicants)
        return FamilyPlan(
            family=family,
            n_applicants=n,
            episodes_min=episodes,
            episodes_max=episodes,
            exact=True,
        )

    if family is Family.SERIALIZATION:
        # The TABLE anchor is executed once and reused by both contrasts, which is the whole
        # point of the shared seed group.
        episodes = sum(k_trials * (1 + len(build_serialization_plans(a))) for a in applicants)
        return FamilyPlan(
            family=family,
            n_applicants=n,
            episodes_min=episodes,
            episodes_max=episodes,
            exact=True,
            note="one shared TABLE anchor per applicant",
        )

    if family is Family.COUNTERFACTUAL_BIAS:
        episodes = 0
        for applicant in applicants:
            plans = 1 + len(build_demographic_plans(applicant))
            episodes += 2 * k_trials * plans
        return FamilyPlan(
            family=family,
            n_applicants=n,
            episodes_min=episodes,
            episodes_max=episodes,
            exact=True,
            note="authority plus rotated demographic contrasts",
        )

    if family is Family.REASON_VALIDITY:
        lower = 0
        upper = 0
        for applicant in applicants:
            low, high = _reason_validity_bounds(applicant, policy, k_trials)
            lower += low
            upper += high
        return FamilyPlan(
            family=family,
            n_applicants=n,
            episodes_min=lower,
            episodes_max=upper,
            exact=False,
            note="pairs depend on the reasons the agent actually cites",
        )

    raise AssertionError(f"unhandled family: {family}")  # pragma: no cover


def build_run_plan(
    suite: Suite,
    applicants: tuple[Applicant, ...],
    policy: Policy,
) -> RunPlan:
    return RunPlan(
        suite=suite.name,
        n_applicants=len(applicants),
        k_trials=suite.k_trials,
        families=tuple(
            plan_family(family, applicants, policy, k_trials=suite.k_trials)
            for family in suite.families
        ),
    )


def format_plan(plan: RunPlan) -> str:
    """Human-readable dry run. Printed by ``credit-audit run --dry-run``."""

    lines = [
        f"suite {plan.suite}: {plan.n_applicants} applicants, k={plan.k_trials}",
        "",
        f"  {'family':<22} {'applicants':>10} {'episodes':>18}",
    ]
    for family in plan.families:
        if family.exact:
            episodes = str(family.episodes_min)
        else:
            episodes = f"{family.episodes_min}-{family.episodes_max}"
        lines.append(f"  {str(family.family):<22} {family.n_applicants:>10} {episodes:>18}")
        if family.note:
            lines.append(f"  {'':<22} {'':>10}   ({family.note})")
    total = (
        str(plan.episodes_min)
        if plan.exact
        else f"{plan.episodes_min}-{plan.episodes_max} (upper bound enforced by the budget)"
    )
    lines.extend(["", f"  total episodes: {total}"])
    return "\n".join(lines)


__all__ = ["FamilyPlan", "RunPlan", "build_run_plan", "format_plan", "plan_family"]
