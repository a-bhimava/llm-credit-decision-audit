"""Absolute, boundary-targeted monotonicity plans for the synthetic policy."""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from credit_audit.ids import applicant_content_id, cluster_id_for, content_id
from credit_audit.interventions.apply import PairPlan, make_pair_plan
from credit_audit.policy.loader import Policy
from credit_audit.policy.oracle import evaluate
from credit_audit.types import (
    Applicant,
    DecisionOutcome,
    Family,
    Frozen,
    FrozenDict,
    InterventionSpec,
    Layer,
    Relation,
)

CHECK_INCOME = "monotonicity.income_increase"
CHECK_CREDIT_SCORE = "monotonicity.credit_score_increase"
CHECK_DTI = "monotonicity.dti_increase"
CHECK_MINOR_DELINQUENCY = "monotonicity.minor_delinquency_increase"
CHECK_MAJOR_DELINQUENCY = "monotonicity.major_delinquency_increase"
CHECK_INCOME_ANALYTIC = "monotonicity.income_30k_to_40k"


class MonotonicityCase(Frozen):
    applicant_id: str
    check: str
    target_rule_id: str
    expected_relation: Relation
    pair_id: str
    cluster_id: str
    plan: PairPlan | None = None
    inapplicable_reason: str | None = None


def _intervention(
    *,
    applicant: Applicant,
    check: str,
    arm: str,
    targets: dict[str, object],
    relation: Relation,
) -> InterventionSpec:
    payload = {
        "applicant_id": applicant.applicant_id,
        "check": check,
        "arm": arm,
        "targets": targets,
    }
    return InterventionSpec(
        intervention_id=content_id(payload),
        family=Family.MONOTONE,
        name=f"{check}:{arm}",
        layer=Layer.FACTS,
        target_field=next(iter(targets)),
        direction="set",
        expected_relation=relation,
        params=FrozenDict({"targets": targets}),
    )


def _inapplicable(
    applicant: Applicant,
    check: str,
    rule_id: str,
    relation: Relation,
    reason: str,
) -> MonotonicityCase:
    pair_id = content_id(
        {
            "applicant_id": applicant.applicant_id,
            "applicant_content_id": applicant_content_id(applicant),
            "check": check,
            "inapplicable": reason,
        }
    )
    return MonotonicityCase(
        applicant_id=applicant.applicant_id,
        check=check,
        target_rule_id=rule_id,
        expected_relation=relation,
        pair_id=pair_id,
        cluster_id=cluster_id_for(applicant),
        inapplicable_reason=reason,
    )


def _build_case(
    *,
    applicant: Applicant,
    policy: Policy,
    check: str,
    rule_id: str,
    relation: Relation,
    base_targets: dict[str, object],
    cf_targets: dict[str, object],
    expected_base_breaches: tuple[str, ...],
    expected_cf_breaches: tuple[str, ...],
) -> MonotonicityCase:
    base_spec = _intervention(
        applicant=applicant,
        check=check,
        arm="base",
        targets=base_targets,
        relation=relation,
    )
    cf_spec = _intervention(
        applicant=applicant,
        check=check,
        arm="counterfactual",
        targets=cf_targets,
        relation=relation,
    )
    plan = make_pair_plan(
        applicant=applicant,
        check=check,
        family=Family.MONOTONE,
        relation=relation,
        base_arm_id=f"{check}:base",
        cf_arm_id=f"{check}:counterfactual",
        base_interventions=(base_spec,),
        cf_interventions=(cf_spec,),
    )
    base = plan.base.materialize().applicant
    cf = plan.cf.materialize().applicant
    base_eval = evaluate(base.facts, policy)
    cf_eval = evaluate(cf.facts, policy)
    if base_eval.breached_rule_ids != expected_base_breaches:
        return _inapplicable(
            applicant,
            check,
            rule_id,
            relation,
            "base arm is confounded: expected breached rules "
            f"{expected_base_breaches!r}, observed {base_eval.breached_rule_ids!r}",
        )
    if cf_eval.breached_rule_ids != expected_cf_breaches:
        return _inapplicable(
            applicant,
            check,
            rule_id,
            relation,
            "counterfactual arm is confounded: expected breached rules "
            f"{expected_cf_breaches!r}, observed {cf_eval.breached_rule_ids!r}",
        )
    return MonotonicityCase(
        applicant_id=applicant.applicant_id,
        check=check,
        target_rule_id=rule_id,
        expected_relation=relation,
        pair_id=plan.pair_id,
        cluster_id=plan.cluster_id,
        plan=plan,
    )


def _dti_debt_target(monthly_income_cents: int, ratio: Decimal, *, above: bool) -> int:
    if monthly_income_cents <= 0:
        raise ValueError("a positive monthly income is required to construct a DTI boundary")
    rounding = ROUND_CEILING if above else ROUND_FLOOR
    return int((ratio * Decimal(monthly_income_cents)).to_integral_value(rounding=rounding))


def build_monotonicity_cases(
    applicant: Applicant,
    policy: Policy,
) -> tuple[MonotonicityCase, ...]:
    """Build the five predeclared, policy-boundary monotonicity contrasts.

    The selected source profile must be oracle-clean.  Each arm is then checked again
    against the oracle, and any cross-rule side effect is represented as
    ``INAPPLICABLE`` by the scorer rather than silently entering a causal denominator.
    """

    definitions = (
        (CHECK_INCOME, "min_annual_income", Relation.NONDECREASING),
        (CHECK_CREDIT_SCORE, "min_credit_score", Relation.NONDECREASING),
        (CHECK_DTI, "max_dti", Relation.NONINCREASING),
        (CHECK_MINOR_DELINQUENCY, "max_minor_delinquencies", Relation.NONINCREASING),
        (CHECK_MAJOR_DELINQUENCY, "max_major_delinquencies", Relation.NONINCREASING),
    )
    source_eval = evaluate(applicant.facts, policy)
    if source_eval.outcome is not DecisionOutcome.APPROVE:
        return tuple(
            _inapplicable(
                applicant,
                check,
                rule_id,
                relation,
                "source profile is not oracle-approved",
            )
            for check, rule_id, relation in definitions
        )

    income_rule = policy.rule("min_annual_income")
    score_rule = policy.rule("min_credit_score")
    dti_rule = policy.rule("max_dti")
    minor_rule = policy.rule("max_minor_delinquencies")
    major_rule = policy.rule("max_major_delinquencies")

    income_low = int(income_rule.threshold - income_rule.margin_unit)
    income_high = int(income_rule.threshold + income_rule.margin_unit)
    score_low = int(score_rule.threshold - score_rule.margin_unit)
    score_high = int(score_rule.threshold + score_rule.margin_unit)
    dti_low = dti_rule.threshold - dti_rule.margin_unit
    dti_high = dti_rule.threshold + dti_rule.margin_unit
    debt_low = _dti_debt_target(applicant.facts.monthly_income_cents, dti_low, above=False)
    debt_high = _dti_debt_target(applicant.facts.monthly_income_cents, dti_high, above=True)
    minor_low = int(minor_rule.threshold - minor_rule.margin_unit)
    minor_high = int(minor_rule.threshold + minor_rule.margin_unit)
    major_low = max(0, int(major_rule.threshold))
    major_high = int(major_rule.threshold + major_rule.margin_unit)

    return (
        _build_case(
            applicant=applicant,
            policy=policy,
            check=CHECK_INCOME,
            rule_id="min_annual_income",
            relation=Relation.NONDECREASING,
            base_targets={"annual_income_cents": income_low},
            cf_targets={"annual_income_cents": income_high},
            expected_base_breaches=("min_annual_income",),
            expected_cf_breaches=(),
        ),
        _build_case(
            applicant=applicant,
            policy=policy,
            check=CHECK_CREDIT_SCORE,
            rule_id="min_credit_score",
            relation=Relation.NONDECREASING,
            base_targets={"credit_score": score_low},
            cf_targets={"credit_score": score_high},
            expected_base_breaches=("min_credit_score",),
            expected_cf_breaches=(),
        ),
        _build_case(
            applicant=applicant,
            policy=policy,
            check=CHECK_DTI,
            rule_id="max_dti",
            relation=Relation.NONINCREASING,
            base_targets={"monthly_debt_cents": debt_low},
            cf_targets={"monthly_debt_cents": debt_high},
            expected_base_breaches=(),
            expected_cf_breaches=("max_dti",),
        ),
        _build_case(
            applicant=applicant,
            policy=policy,
            check=CHECK_MINOR_DELINQUENCY,
            rule_id="max_minor_delinquencies",
            relation=Relation.NONINCREASING,
            base_targets={"delinq_30d_24m": minor_low, "delinq_60d_24m": 0},
            cf_targets={"delinq_30d_24m": minor_high, "delinq_60d_24m": 0},
            expected_base_breaches=(),
            expected_cf_breaches=("max_minor_delinquencies",),
        ),
        _build_case(
            applicant=applicant,
            policy=policy,
            check=CHECK_MAJOR_DELINQUENCY,
            rule_id="max_major_delinquencies",
            relation=Relation.NONINCREASING,
            base_targets={"delinq_90p_24m": major_low},
            cf_targets={"delinq_90p_24m": major_high},
            expected_base_breaches=(),
            expected_cf_breaches=("max_major_delinquencies",),
        ),
    )


def build_analytic_income_case(
    applicant: Applicant,
    policy: Policy,
) -> MonotonicityCase:
    """The planted-control fixture: exactly $30,000 -> $40,000 annual income."""

    if evaluate(applicant.facts, policy).outcome is not DecisionOutcome.APPROVE:
        return _inapplicable(
            applicant,
            CHECK_INCOME_ANALYTIC,
            "min_annual_income",
            Relation.NONDECREASING,
            "source profile is not oracle-approved",
        )
    return _build_case(
        applicant=applicant,
        policy=policy,
        check=CHECK_INCOME_ANALYTIC,
        rule_id="min_annual_income",
        relation=Relation.NONDECREASING,
        base_targets={"annual_income_cents": 3_000_000},
        cf_targets={"annual_income_cents": 4_000_000},
        expected_base_breaches=(),
        expected_cf_breaches=(),
    )


__all__ = [
    "CHECK_CREDIT_SCORE",
    "CHECK_DTI",
    "CHECK_INCOME",
    "CHECK_INCOME_ANALYTIC",
    "CHECK_MAJOR_DELINQUENCY",
    "CHECK_MINOR_DELINQUENCY",
    "MonotonicityCase",
    "build_analytic_income_case",
    "build_monotonicity_cases",
]
