"""Shared trial-index-aligned scoring for paired audit checks.

The unit of evidence in this project is a *matched trial*, not two independently
estimated rates.  This module is deliberately small and policy-agnostic so reason
repair, monotonicity, invariance, serialization, and bias checks all use the same
completion and discordance semantics.

Only an explicit approval is classified as :class:`OutcomeClass.APPROVE`.  A denial,
or a counteroffer already marked as adverse by the decision parser, is
:class:`OutcomeClass.ADVERSE`.  Refusals, missing decisions, referrals, indeterminate
counteroffers, and every other non-decision are :class:`OutcomeClass.NO_DECISION`.

Pairs align on ``EpisodeKey.trial_index``.  A trial contributes to rates only when both
legs have a decisive outcome.  Bilateral non-decisions are excluded and disclosed;
any unilateral non-decision invalidates the pair-level inference and is surfaced via
``has_unilateral_incomplete`` for the caller to turn into ``TestStatus.ERROR``.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from credit_audit.ids import applicant_content_id, episode_input_hash
from credit_audit.interventions.apply import ArmPlan, PairPlan
from credit_audit.policy.loader import Policy
from credit_audit.render.packet import RenderOptions
from credit_audit.render.reference import applicant_reference_for
from credit_audit.render.registry import render_application
from credit_audit.types import Frozen, FrozenDict, Relation, Termination, Trajectory


class OutcomeClass(StrEnum):
    APPROVE = "APPROVE"
    ADVERSE = "ADVERSE"
    NO_DECISION = "NO_DECISION"


class DecisionSignature(Frozen):
    """The normalized, provider-independent decision signature for invariance checks."""

    outcome: OutcomeClass
    apr_bps: int | None = None
    credit_limit_cents: int | None = None
    risk_grade: str | None = None
    reason_codes: tuple[str, ...] = ()


def classify_trajectory(trajectory: Trajectory) -> OutcomeClass:
    """Classify one trajectory without treating referral as an approval.

    ``is_adverse_action`` is consulted only for counteroffers.  DENY and APPROVE are
    explicit outcomes and therefore remain decisive even if a malformed provider
    payload supplied an inconsistent convenience flag.
    """

    if trajectory.termination is not Termination.SUBMITTED:
        return OutcomeClass.NO_DECISION
    decision = trajectory.decision
    if decision is None:
        return OutcomeClass.NO_DECISION
    if decision.outcome.value == "APPROVE":
        return OutcomeClass.APPROVE
    if decision.outcome.value == "DENY":
        return OutcomeClass.ADVERSE
    if decision.outcome.value == "COUNTEROFFER" and decision.is_adverse_action:
        return OutcomeClass.ADVERSE
    return OutcomeClass.NO_DECISION


def decision_signature(trajectory: Trajectory) -> DecisionSignature | None:
    """Return a comparable signature, or ``None`` for a non-decision trajectory."""

    outcome = classify_trajectory(trajectory)
    if outcome is OutcomeClass.NO_DECISION or trajectory.decision is None:
        return None
    decision = trajectory.decision
    ordered_reasons = tuple(
        reason.code.value
        for reason in sorted(decision.stated_reasons, key=lambda reason: reason.rank)
    )
    return DecisionSignature(
        outcome=outcome,
        apr_bps=decision.apr_bps,
        credit_limit_cents=decision.credit_limit_cents,
        risk_grade=decision.risk_grade,
        reason_codes=ordered_reasons,
    )


class PairedScore(Frozen):
    """Aggregate metrics over trial-index-aligned decisive pairs."""

    planned_trials: int
    matched_trials: int
    base_completed: int
    cf_completed: int
    bilateral_incomplete: int
    unilateral_incomplete: int
    pair_completion_rate: float
    base_approve_rate: float | None
    cf_approve_rate: float | None
    effect: float | None
    adverse_to_approve: int
    approve_to_adverse: int
    reason_signature_changes: int
    decision_signature_changes: int

    @property
    def has_unilateral_incomplete(self) -> bool:
        return self.unilateral_incomplete > 0

    @property
    def base_completion_rate(self) -> float:
        return self.base_completed / self.planned_trials if self.planned_trials else 0.0

    @property
    def cf_completion_rate(self) -> float:
        return self.cf_completed / self.planned_trials if self.planned_trials else 0.0

    @property
    def discordant_b(self) -> int:
        """McNemar ``b`` cell: base approval changed to counterfactual adverse."""

        return self.approve_to_adverse

    @property
    def discordant_c(self) -> int:
        """McNemar ``c`` cell: base adverse changed to counterfactual approval."""

        return self.adverse_to_approve

    def relation_holds(self, relation: Relation, *, delta: float = 0.0) -> bool | None:
        """Evaluate a declared relation, or return ``None`` when evidence is invalid.

        ``delta`` is a tolerated rate movement for monotone/invariant checks and the
        minimum required approval-rate increase for ``FLIP_TO_APPROVE``.
        """

        if self.has_unilateral_incomplete or self.matched_trials == 0 or self.effect is None:
            return None
        if relation is Relation.NONDECREASING:
            return self.effect >= -delta
        if relation is Relation.NONINCREASING:
            return self.effect <= delta
        if relation is Relation.INVARIANT:
            return self.decision_signature_changes == 0
        if relation is Relation.FLIP_TO_APPROVE:
            return self.effect >= delta
        if relation is Relation.UNCONSTRAINED:
            return True
        raise AssertionError(f"unhandled relation: {relation}")  # pragma: no cover

    def observed(self) -> FrozenDict:
        """Stable export-ready metrics shared by every paired check."""

        return FrozenDict(
            {
                "planned_trials": self.planned_trials,
                "matched_trials": self.matched_trials,
                "base_completed": self.base_completed,
                "cf_completed": self.cf_completed,
                "base_completion_rate": self.base_completion_rate,
                "cf_completion_rate": self.cf_completion_rate,
                "bilateral_incomplete": self.bilateral_incomplete,
                "unilateral_incomplete": self.unilateral_incomplete,
                "pair_completion_rate": self.pair_completion_rate,
                "base_approve_rate": self.base_approve_rate,
                "cf_approve_rate": self.cf_approve_rate,
                "effect": self.effect,
                "adverse_to_approve": self.adverse_to_approve,
                "approve_to_adverse": self.approve_to_adverse,
                "discordant_b": self.discordant_b,
                "discordant_c": self.discordant_c,
                "reason_signature_changes": self.reason_signature_changes,
                "decision_signature_changes": self.decision_signature_changes,
            }
        )


def _by_trial_index(trajectories: tuple[Trajectory, ...], *, leg: str) -> dict[int, Trajectory]:
    indexed: dict[int, Trajectory] = {}
    for trajectory in trajectories:
        trial_index = trajectory.key.trial_index
        if trial_index in indexed:
            raise ValueError(f"duplicate {leg} trajectory for trial_index={trial_index}")
        indexed[trial_index] = trajectory
    return indexed


def _validate_matched_keys(base: Trajectory, cf: Trajectory) -> None:
    """Require the common-random-number and shared-context pairing contract."""

    mismatches: list[str] = []
    if base.key.applicant_id != cf.key.applicant_id:
        mismatches.append("applicant_id")
    if base.key.model_id != cf.key.model_id:
        mismatches.append("model_id")
    if base.key.prompt_hash != cf.key.prompt_hash:
        mismatches.append("prompt_hash")
    if base.key.seed != cf.key.seed:
        mismatches.append("seed")
    if base.key.arm_id == cf.key.arm_id:
        mismatches.append("distinct arm_id")
    if mismatches:
        raise ValueError(
            f"trial_index={base.key.trial_index} is not a valid matched pair; "
            "mismatched " + ", ".join(mismatches)
        )


def validate_trajectory_collection(
    applicant,
    render_mode,
    trajectories: tuple[Trajectory, ...],
    *,
    leg: str,
    policy: Policy,
    render_options: RenderOptions | None = None,
    expected_arm_id: str | None = None,
    expected_seed: Callable[[int], int] | None = None,
) -> None:
    """Bind a trajectory collection to its materialized applicant and visible input.

    Relative pair checks cannot detect relabeling otherwise valid evidence under a different
    applicant or plan. This boundary recomputes the canonical provider-visible input and can
    additionally enforce a planned arm and seed schedule.
    """

    expected_content_id = applicant_content_id(applicant)
    expected_ref = applicant_reference_for(applicant)
    expected_application_text = render_application(
        applicant,
        render_mode,
        policy,
        options=render_options,
    )
    expected_input_hash = episode_input_hash(
        applicant,
        application_text=expected_application_text,
        applicant_ref=expected_ref,
        render_mode=render_mode,
    )
    for trajectory in trajectories:
        key = trajectory.key
        mismatches: list[str] = []
        if key.applicant_id != applicant.applicant_id:
            mismatches.append("applicant_id")
        if key.applicant_content_id != expected_content_id:
            mismatches.append("applicant_content_id")
        if expected_arm_id is not None and key.arm_id != expected_arm_id:
            mismatches.append("arm_id")
        if key.render_id is not render_mode:
            mismatches.append("render_id")
        if key.input_hash != expected_input_hash:
            mismatches.append("input_hash")
        if expected_seed is not None and key.seed != expected_seed(key.trial_index):
            mismatches.append("seed")
        if mismatches:
            raise ValueError(
                f"{leg} trial_index={key.trial_index} does not match expected evidence; "
                "mismatched " + ", ".join(mismatches)
            )


def _validate_arm_trajectories(
    plan: PairPlan,
    arm: ArmPlan,
    trajectories: tuple[Trajectory, ...],
    *,
    leg: str,
    run_seed: int,
    policy: Policy,
) -> None:
    materialized = arm.materialize()
    validate_trajectory_collection(
        materialized.applicant,
        arm.render_mode,
        trajectories,
        leg=f"PairPlan {leg}",
        policy=policy,
        render_options=materialized.render_options,
        expected_arm_id=arm.arm_id,
        expected_seed=lambda trial_index: plan.trial_seed(run_seed, trial_index),
    )


def validate_pair_plan_trajectories(
    plan: PairPlan,
    base_trajectories: tuple[Trajectory, ...],
    cf_trajectories: tuple[Trajectory, ...],
    *,
    run_seed: int,
    policy: Policy,
) -> None:
    """Validate that both evidence collections realize exactly the supplied plan."""

    _validate_arm_trajectories(
        plan,
        plan.base,
        base_trajectories,
        leg="base",
        run_seed=run_seed,
        policy=policy,
    )
    _validate_arm_trajectories(
        plan,
        plan.cf,
        cf_trajectories,
        leg="counterfactual",
        run_seed=run_seed,
        policy=policy,
    )


def score_paired_trajectories(
    base_trajectories: tuple[Trajectory, ...],
    cf_trajectories: tuple[Trajectory, ...],
    *,
    planned_trials: int | None = None,
) -> PairedScore:
    """Align two legs by trial index and compute rates over matched decisive trials.

    Pass ``planned_trials`` when the execution plan is known so a trial missing from
    both result collections is still represented as a bilateral incompletion.  Without
    it, the union of observed trial indices is the disclosed denominator.
    """

    base_by_index = _by_trial_index(base_trajectories, leg="base")
    cf_by_index = _by_trial_index(cf_trajectories, leg="counterfactual")
    observed_indices = set(base_by_index) | set(cf_by_index)

    if planned_trials is None:
        indices = tuple(sorted(observed_indices))
        planned = len(indices)
    else:
        if planned_trials < 0:
            raise ValueError("planned_trials must be non-negative")
        indices = tuple(range(planned_trials))
        unexpected = observed_indices - set(indices)
        if unexpected:
            raise ValueError(
                "trajectory trial indices fall outside planned range: "
                + ", ".join(str(index) for index in sorted(unexpected))
            )
        planned = planned_trials

    matched = 0
    base_completed = 0
    cf_completed = 0
    bilateral_incomplete = 0
    unilateral_incomplete = 0
    base_approvals = 0
    cf_approvals = 0
    adverse_to_approve = 0
    approve_to_adverse = 0
    reason_signature_changes = 0
    decision_signature_changes = 0

    for trial_index in indices:
        base = base_by_index.get(trial_index)
        cf = cf_by_index.get(trial_index)
        if base is not None and cf is not None:
            _validate_matched_keys(base, cf)
        base_signature = decision_signature(base) if base is not None else None
        cf_signature = decision_signature(cf) if cf is not None else None
        base_decisive = base_signature is not None
        cf_decisive = cf_signature is not None
        base_completed += int(base_decisive)
        cf_completed += int(cf_decisive)

        if not base_decisive and not cf_decisive:
            bilateral_incomplete += 1
            continue
        if base_decisive != cf_decisive:
            unilateral_incomplete += 1
            continue

        assert base_signature is not None and cf_signature is not None
        matched += 1
        base_is_approve = base_signature.outcome is OutcomeClass.APPROVE
        cf_is_approve = cf_signature.outcome is OutcomeClass.APPROVE
        base_approvals += int(base_is_approve)
        cf_approvals += int(cf_is_approve)
        if not base_is_approve and cf_is_approve:
            adverse_to_approve += 1
        elif base_is_approve and not cf_is_approve:
            approve_to_adverse += 1
        if base_signature.reason_codes != cf_signature.reason_codes:
            reason_signature_changes += 1
        if base_signature != cf_signature:
            decision_signature_changes += 1

    pair_completion_rate = matched / planned if planned else 0.0
    if matched:
        base_approve_rate: float | None = base_approvals / matched
        cf_approve_rate: float | None = cf_approvals / matched
        effect: float | None = cf_approve_rate - base_approve_rate
    else:
        base_approve_rate = None
        cf_approve_rate = None
        effect = None

    return PairedScore(
        planned_trials=planned,
        matched_trials=matched,
        base_completed=base_completed,
        cf_completed=cf_completed,
        bilateral_incomplete=bilateral_incomplete,
        unilateral_incomplete=unilateral_incomplete,
        pair_completion_rate=pair_completion_rate,
        base_approve_rate=base_approve_rate,
        cf_approve_rate=cf_approve_rate,
        effect=effect,
        adverse_to_approve=adverse_to_approve,
        approve_to_adverse=approve_to_adverse,
        reason_signature_changes=reason_signature_changes,
        decision_signature_changes=decision_signature_changes,
    )


__all__ = [
    "DecisionSignature",
    "OutcomeClass",
    "PairedScore",
    "classify_trajectory",
    "decision_signature",
    "score_paired_trajectories",
    "validate_pair_plan_trajectories",
    "validate_trajectory_collection",
]
