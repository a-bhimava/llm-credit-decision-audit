"""Executes a breached rule's repair -- the mechanical "move this applicant past this
rule's threshold" step Phase 5's reason-validity check runs, for every currently-breached
rule under a cited code, to test whether the reason was actually binding.

Every repair overshoots 20% past the threshold, never sits on it -- the boundary is where
agent noise dominates (``docs/roadmap.md``'s Phase 4 non-obvious requirement). Repairs set
``FinancialFacts`` primitives only; every derived quantity (``dti``, ``cltv``,
``utilization``, ``loan_to_income``, ``delinq_minor_count_24m``) recomputes automatically
from the primitive, so a repaired applicant is never left holding a stale ratio (see
``types.py``'s invariant 2).

**Two hazards a naive implementation hits, both fixed here, not left as follow-up:**

1. Three rules (``max_dti``, ``max_loan_to_income``, ``max_revolving_utilization``) read a
   RATIO accessor but repair a DIFFERENT single field -- one operand of that ratio, not the
   ratio itself. Applying ``threshold * 0.8`` directly to the repair field is dimensionally
   wrong (e.g. ``max_dti``: ``0.43 * 0.8 = 0.344``, which would set
   ``monthly_debt_cents`` to 34 cents, not 34.4% of income). ``_RATIO_INVERTERS`` solves
   for the correct field against the applicant's own CURRENT value of the field NOT being
   repaired.
2. A code covering more than one simultaneously-breached rule that share a field
   (``INSUFFICIENT_INCOME``: ``min_annual_income`` and ``max_loan_to_income`` both raise
   ``annual_income_cents``, but compute independent targets) cannot be repaired by applying
   each rule's update sequentially -- whichever runs last silently overwrites the other,
   and can leave the first rule still breached (verified against the real oracle during
   design: income=$15,000/loan=$9,000 breaches both; sequential repair left income at
   $22,500, still below the $24,000 floor). ``repair_code`` computes every rule's target
   against the ORIGINAL facts (never chained) and merges same-field targets via ``max()``
   (increase direction) / ``min()`` (decrease direction) before a single write.

Deliberately does NOT reuse ``policy/boundary.py``'s ``set_dti``/``set_loan_to_income``/
``set_utilization``: those assert an exact-integer-cents result, which is fine for
hand-picked Phase 1/3 fixtures but would crash against an arbitrary generated applicant's
income (this needs floor/ceil rounding, not an exactness guarantee), and
``set_loan_to_income`` solves for ``loan_amount_cents`` -- the right lever for constructing
a Phase 3 breach fixture, the wrong field for this repair (``policy.yaml``'s actual repair
for ``max_loan_to_income`` is ``annual_income_cents``). ``set_minor_delinquencies``'s
convention (put the whole target in the first field, zero the rest) IS mirrored below,
byte-for-byte, for the one multi-field case -- no ratio math there to go wrong.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any

from credit_audit.policy.loader import Policy
from credit_audit.policy.oracle import GroundTruthDecision, RuleEvaluation, clears, evaluate
from credit_audit.types import EmploymentStatus, FinancialFacts, ReasonCode

OVERSHOOT_FACTOR = Decimal("0.20")


def _clamp_int(value: int, policy: Policy, field_name: str) -> int:
    spec = policy.field(field_name)
    if spec.plausible_range is None:
        return value
    lo, hi = (int(b) for b in spec.plausible_range)
    return min(hi, max(lo, value))


def _target_ratio(threshold: Decimal, direction: str) -> Decimal:
    factor = (
        Decimal(1) + OVERSHOOT_FACTOR if direction == "increase" else Decimal(1) - OVERSHOOT_FACTOR
    )
    return threshold * factor


def _repair_max_dti(facts: FinancialFacts, threshold: Decimal, policy: Policy) -> dict[str, Any]:
    ratio = _target_ratio(threshold, "decrease")
    target = int(
        (ratio * Decimal(facts.monthly_income_cents)).to_integral_value(rounding=ROUND_FLOOR)
    )
    return {"monthly_debt_cents": max(0, _clamp_int(target, policy, "monthly_debt_cents"))}


def _repair_max_loan_to_income(
    facts: FinancialFacts, threshold: Decimal, policy: Policy
) -> dict[str, Any]:
    ratio = _target_ratio(threshold, "decrease")  # a LOWER ratio needs HIGHER income
    target = int(
        (Decimal(facts.loan_amount_cents) / ratio).to_integral_value(rounding=ROUND_CEILING)
    )
    return {"annual_income_cents": _clamp_int(target, policy, "annual_income_cents")}


def _repair_max_revolving_utilization(
    facts: FinancialFacts, threshold: Decimal, policy: Policy
) -> dict[str, Any]:
    ratio = _target_ratio(threshold, "decrease")
    target = int(
        (ratio * Decimal(facts.revolving_limit_cents)).to_integral_value(rounding=ROUND_FLOOR)
    )
    return {
        "revolving_balance_cents": max(0, _clamp_int(target, policy, "revolving_balance_cents"))
    }


_RATIO_INVERTERS: dict[str, Callable[[FinancialFacts, Decimal, Policy], dict[str, Any]]] = {
    "max_dti": _repair_max_dti,
    "max_loan_to_income": _repair_max_loan_to_income,
    "max_revolving_utilization": _repair_max_revolving_utilization,
}


def _repair_threshold_cross(
    facts: FinancialFacts, rule_eval: RuleEvaluation, policy: Policy
) -> dict[str, Any]:
    if rule_eval.rule_id in _RATIO_INVERTERS:
        return _RATIO_INVERTERS[rule_eval.rule_id](facts, rule_eval.threshold, policy)

    fields = rule_eval.repair.fields
    threshold = rule_eval.threshold
    direction = rule_eval.repair.direction

    if threshold == 0:
        # No percentage math is possible below zero for a count field -- 0 is already the
        # extreme compliant value. max_major_delinquencies is the only rule this applies
        # to today (verified: the only rule with threshold "0").
        target = 0
    elif direction == "increase":
        target = int(
            (threshold * (Decimal(1) + OVERSHOOT_FACTOR)).to_integral_value(rounding=ROUND_CEILING)
        )
    else:
        target = int(
            (threshold * (Decimal(1) - OVERSHOOT_FACTOR)).to_integral_value(rounding=ROUND_FLOOR)
        )

    if len(fields) == 1:
        field_name = fields[0]
        return {field_name: max(0, _clamp_int(target, policy, field_name))}

    # The one multi-field case: max_minor_delinquencies (delinq_30d_24m + delinq_60d_24m),
    # direction=decrease. Mirrors policy/boundary.py::set_minor_delinquencies's own
    # established convention exactly: the whole target sum goes in the first field, the
    # rest are zeroed -- not reinvented here.
    first_field, *rest_fields = fields
    target = max(0, target)
    updates: dict[str, Any] = {first_field: target}
    updates.update(dict.fromkeys(rest_fields, 0))
    return updates


def _repair_enum_set(rule_eval: RuleEvaluation) -> dict[str, Any]:
    field_name = rule_eval.repair.fields[0]
    return {field_name: EmploymentStatus(rule_eval.repair.params["enum_target"])}


def _repair_flag_set(rule_eval: RuleEvaluation) -> dict[str, Any]:
    field_name = rule_eval.repair.fields[0]
    return {field_name: bool(rule_eval.repair.params["flag_target"])}


def _repair_record_remove(facts: FinancialFacts, rule_eval: RuleEvaluation) -> dict[str, Any]:
    remove_kinds = set(rule_eval.repair.params["remove_kinds"])
    kept = tuple(r for r in facts.public_records if r.kind.value not in remove_kinds)
    return {"public_records": kept}


def repair_rule(facts: FinancialFacts, rule_eval: RuleEvaluation, policy: Policy) -> dict[str, Any]:
    """Pure: computes the ``{field: value}`` update for ONE rule, against the given facts
    snapshot -- never calls ``model_copy``. :func:`repair_code` owns merging same-field
    updates across rules and writing the result once."""
    kind = rule_eval.repair.kind
    if kind == "threshold_cross":
        return _repair_threshold_cross(facts, rule_eval, policy)
    if kind == "enum_set":
        return _repair_enum_set(rule_eval)
    if kind == "flag_set":
        return _repair_flag_set(rule_eval)
    if kind == "record_remove":
        return _repair_record_remove(facts, rule_eval)
    raise AssertionError(f"unhandled repair kind: {kind!r}")  # pragma: no cover


def repair_code(
    facts: FinancialFacts,
    code: ReasonCode,
    decision: GroundTruthDecision,
    policy: Policy,
) -> FinancialFacts:
    """Repairs every rule in ``decision.breached_by_code[code]`` at once. Each rule's
    target is computed against the ORIGINAL ``facts`` (never chained through an
    intermediate ``model_copy``), then merged -- ``max()`` for an increase-direction field,
    ``min()`` for decrease -- before a single write. Self-checks via
    :func:`credit_audit.policy.oracle.clears` before returning: a bug in this module's own
    math fails loudly here, at the point of the bug, rather than silently three phases
    later as a false "unrepairable reason" finding in Phase 5.
    """
    breached_evals = decision.breached_by_code.get(code, ())
    if not breached_evals:
        return facts

    updates: dict[str, Any] = {}
    remove_kinds: set[str] = set()
    for rule_eval in breached_evals:
        if rule_eval.repair.kind == "record_remove":
            remove_kinds |= set(rule_eval.repair.params["remove_kinds"])
            continue
        rule_updates = repair_rule(facts, rule_eval, policy)
        direction = rule_eval.repair.direction
        for field_name, value in rule_updates.items():
            if field_name not in updates:
                updates[field_name] = value
            elif direction == "increase":
                updates[field_name] = max(updates[field_name], value)
            elif direction == "decrease":
                updates[field_name] = min(updates[field_name], value)
            else:
                updates[field_name] = value

    if remove_kinds:
        kept = tuple(r for r in facts.public_records if r.kind.value not in remove_kinds)
        updates["public_records"] = kept

    repaired = facts.model_copy(update=updates)
    after = evaluate(repaired, policy)
    if not clears(decision, after, code):
        raise AssertionError(
            f"repair_code({code!r}) failed its own falsifiability guard -- this is a "
            "repair.py bug, not a statement about whether the reason was true"
        )
    return repaired


__all__ = ["OVERSHOOT_FACTOR", "repair_code", "repair_rule"]
