"""Calibration sanity, deliberately lightweight.

A full calibration test would need to sample from a realistic applicant population and
check the aggregate deny rate against `calibration_targets` in policy.yaml -- but no
population exists until Phase 3, and independent-uniform sampling over 16 constraints is
not a stand-in for one (16 independent ~90% per-rule pass rates compound to a deny rate
far outside any reasonable target, which would say more about the sampling than the
policy). This file checks what's checkable now: the targets are declared and sane, the
clean baseline is unambiguously compliant, and -- via the fixture matrix in
test_oracle.py, which already proves it -- every rule has a reachable compliant region
and a reachable breached region. Real calibration against a generated population is a
Phase 3 test.
"""

from __future__ import annotations

from decimal import Decimal

from credit_audit.policy.loader import load_policy
from credit_audit.policy.oracle import evaluate

from .test_oracle import GOLDEN_CLEAN, MATRIX, OVERRIDE_R05


def test_calibration_targets_are_declared_and_sane():
    import yaml

    from credit_audit.policy.loader import YAML_PATH

    source = yaml.safe_load(YAML_PATH.read_text())
    targets = source["calibration_targets"]

    deny = targets["overall_deny_rate"]
    assert Decimal(deny["min"]) < Decimal(deny["max"])
    assert Decimal("0") <= Decimal(deny["min"]) < Decimal(deny["max"]) <= Decimal("1")

    per_rule = targets["per_rule_breach_rate"]
    assert Decimal(per_rule["min"]) < Decimal(per_rule["max"])
    assert Decimal("0") <= Decimal(per_rule["min"]) < Decimal(per_rule["max"]) <= Decimal("1")


def test_every_rule_has_a_reachable_compliant_and_breached_region():
    """A rule whose threshold cannot actually be breached (or cannot actually be
    satisfied) by any constructible FinancialFacts would make its reason code
    permanently unreachable -- silently, since evaluate() would never raise. The
    boundary matrix in test_oracle.py already constructs both a compliant and a
    breaching fixture for all 16 rules; this test just names that guarantee explicitly
    as a calibration property rather than leaving it implicit in the exit criterion.
    """
    policy = load_policy()
    compliant_rules = set()
    breached_rules = set()
    for rule_id, _case, _target, expect_breach in MATRIX:
        (breached_rules if expect_breach else compliant_rules).add(rule_id)
    all_ids = {r.rule_id for r in policy.rules}
    assert compliant_rules == all_ids
    assert breached_rules == all_ids


def test_clean_baselines_clear_every_rule_with_positive_margin():
    """Both hand-written baselines are not merely non-breaching but comfortably so --
    a baseline sitting exactly on a boundary would be a fragile foundation for the
    fixture matrix (a rounding change to margin_unit could flip it)."""
    policy = load_policy()
    for baseline in (GOLDEN_CLEAN, OVERRIDE_R05):
        decision = evaluate(baseline, policy)
        assert decision.outcome.value == "APPROVE"
        for ev in decision.evaluations:
            assert ev.margin >= 0, f"{ev.rule_id} margin {ev.margin} is not comfortably compliant"
