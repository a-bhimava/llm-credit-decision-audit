"""``RepairSpec`` -- a descriptive, per-code summary of what repairing a code would touch.

Deliberately thin: the actual repair execution lives in
:mod:`credit_audit.interventions.repair` (``repair_code``, which needs the full
``GroundTruthDecision`` to know which rules are *actually* breached for a given applicant,
not just which rules a code covers in the abstract). This module answers a narrower,
applicant-independent question -- "if this code were cited, what fields and rules would a
repair touch?" -- useful for documentation, the future evidence site, and any check that
wants to describe a repair before running it.
"""

from __future__ import annotations

from credit_audit.policy.loader import Policy
from credit_audit.reasons.codes import CODE_META
from credit_audit.types import Frozen, ReasonCode


class RepairSpec(Frozen):
    code: ReasonCode
    repairable: bool
    rule_ids: tuple[str, ...]
    target_fields: tuple[str, ...]
    repair_kind: str | None


def repair_spec_for(code: ReasonCode, policy: Policy) -> RepairSpec:
    meta = CODE_META[code]
    rules = policy.rules_for(code)
    return RepairSpec(
        code=code,
        repairable=meta.repairable,
        rule_ids=tuple(r.rule_id for r in rules),
        target_fields=meta.target_fields,
        repair_kind=meta.repair_kind,
    )


__all__ = ["RepairSpec", "repair_spec_for"]
