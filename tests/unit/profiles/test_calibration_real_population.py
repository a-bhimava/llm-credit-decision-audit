"""Real-population calibration: the committed 225-profile fixture, evaluated through the
real Phase 1 oracle, must satisfy policy.yaml's calibration_targets and show a healthy
breach-count spread. This is the Phase 3 test test_calibration.py's own docstring predicted:
"Real calibration against a generated population is a Phase 3 test."
"""

from __future__ import annotations

from decimal import Decimal

from credit_audit.policy.loader import load_policy
from credit_audit.policy.oracle import evaluate
from credit_audit.profiles.generate import read_profiles_jsonl
from credit_audit.profiles.selection import CALIBRATION_SAFETY_MARGIN, load_calibration_targets
from credit_audit.types import DecisionOutcome


def _decisions():
    policy = load_policy()
    profiles = read_profiles_jsonl()
    decisions = [evaluate(a.facts, policy) for a in profiles]
    return policy, profiles, decisions


def test_generated_population_meets_calibration_targets():
    policy, profiles, decisions = _decisions()
    targets = load_calibration_targets()
    n = len(profiles)
    assert n > 0

    deny_rate = Decimal(sum(1 for d in decisions if d.outcome is DecisionOutcome.DENY)) / n
    dr = targets["overall_deny_rate"]
    assert dr["min"] <= deny_rate <= dr["max"], (
        f"deny rate {deny_rate} outside [{dr['min']},{dr['max']}]"
    )

    pr = targets["per_rule_breach_rate"]
    for rule in policy.rules:
        rate = Decimal(sum(1 for d in decisions if rule.rule_id in d.breached_rule_ids)) / n
        assert pr["min"] <= rate <= pr["max"], (
            f"{rule.rule_id} breach rate {rate} outside [{pr['min']},{pr['max']}]"
        )


def test_per_rule_rates_clear_the_declared_bounds_with_real_margin():
    """Not just 'inside [floor, ceiling]' (the test above) -- clears each bound by at
    least CALIBRATION_SAFETY_MARGIN. Two rules (max_dti, min_annual_income) used to sit
    exactly one profile above the floor before Stage C's stopping condition added this
    margin; this pins the fix so a future regeneration can't silently reintroduce that
    brittleness without a test noticing."""
    policy, profiles, decisions = _decisions()
    targets = load_calibration_targets()
    pr = targets["per_rule_breach_rate"]
    n = len(profiles)

    for rule in policy.rules:
        rate = Decimal(sum(1 for d in decisions if rule.rule_id in d.breached_rule_ids)) / n
        assert pr["min"] + CALIBRATION_SAFETY_MARGIN <= rate, (
            f"{rule.rule_id} breach rate {rate} is within {CALIBRATION_SAFETY_MARGIN} of "
            f"the floor {pr['min']} -- too brittle"
        )
        assert rate <= pr["max"] - CALIBRATION_SAFETY_MARGIN, (
            f"{rule.rule_id} breach rate {rate} is within {CALIBRATION_SAFETY_MARGIN} of "
            f"the ceiling {pr['max']} -- too brittle"
        )


def test_presentation_varies_across_the_generated_population():
    """F11: BiasedAgent (the authority-bias positive control) needs
    employer_prestige_tier >= 4 somewhere in the population, or it can never fire against
    real generated profiles. Demographic-independence is preserved -- see
    selection.py's EMPLOYER_PRESTIGE_WEIGHTS comment -- this only checks variation exists."""
    _policy, profiles, _decision_list = _decisions()
    tiers = {a.presentation.employer_prestige_tier for a in profiles}
    names = {a.presentation.employer_name for a in profiles}
    assert len(tiers) > 1, "employer_prestige_tier is constant across the population"
    assert len(names) > 1, "employer_name is constant across the population"
    assert any(a.presentation.employer_prestige_tier >= 4 for a in profiles), (
        "no profile has employer_prestige_tier >= 4 -- BiasedAgent can never fire"
    )


def test_breach_count_distribution_has_a_healthy_spread():
    _policy, _profiles, decisions = _decisions()
    buckets: dict[object, int] = {0: 0, 1: 0, 2: 0, "3+": 0}
    for d in decisions:
        n = len(d.breached)
        buckets[n if n < 3 else "3+"] += 1
    for key, count in buckets.items():
        assert count >= 15, f"breach-count bucket {key!r} has only {count} members"


def test_every_selected_applicant_was_scored_by_the_real_oracle_not_hmda():
    """Provenance sanity: nothing in the committed fixture carries any HMDA outcome field
    at all -- Applicant/FinancialFacts structurally cannot, since neither type has an
    action_taken or denial_reason field. This test exists to name that guarantee, not to
    discover it."""
    from credit_audit.types import Applicant, FinancialFacts

    assert "action_taken" not in FinancialFacts.model_fields
    assert "denial_reason" not in FinancialFacts.model_fields
    assert "action_taken" not in Applicant.model_fields
