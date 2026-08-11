"""Pure construction of Phase 5's causal reason-validity pairs.

Joint sufficiency retains its original question: compare the submitted applicant with a
variant where every cited, genuinely breached reason is repaired.  Necessity and omission
need a stricter isolation contrast.  For a reason ``r`` they compare:

``all real breaches except r repaired`` -> ``all real breaches repaired``.

The left leg therefore has exactly ``r`` remaining when isolation succeeds; the right leg
is oracle-approved.  This catches multiple simultaneous omissions independently, which the
old "add one omitted repair to cited repairs" construction could not do: when two reasons
were omitted, the other omission kept both counterfactuals denied and produced false passes.

Omission candidates are the oracle's ranked unique principal codes, truncated to the
synthetic policy's configured reason maximum.  Real fifth-and-later weaknesses therefore do
not become omissions merely because a faithful agent truthfully applied the policy's cap.
"""

from __future__ import annotations

from pydantic import model_validator

from credit_audit.ids import content_id
from credit_audit.interventions.repair import repair_code
from credit_audit.policy.loader import Policy
from credit_audit.policy.oracle import GroundTruthDecision, cited_not_breached
from credit_audit.types import (
    Applicant,
    Family,
    FinancialFacts,
    Frozen,
    FrozenDict,
    InterventionSpec,
    Layer,
    ReasonCode,
    Relation,
    RenderMode,
)

CHECK_FABRICATION = "reason_validity.fabrication"
CHECK_JOINT_SUFFICIENCY = "reason_validity.joint_sufficiency"
CHECK_NECESSITY_LOO = "reason_validity.necessity_loo"
CHECK_OMISSION_SCAN = "reason_validity.omission_scan"


class CounterfactualSpec(Frozen):
    pair_id: str
    """Deterministic, unique per (applicant, check, construction parameters) -- see module
    docstring. This identifies one contrast; ``cluster_id`` separately identifies the source
    applicant used as the Phase 7 resampling unit."""
    check: str
    applicant_id: str
    source_content_id: str
    render_mode: RenderMode
    held_out_code: ReasonCode | None = None
    """Set for necessity: the cited code isolated as the only remaining breach."""
    omitted_code: ReasonCode | None = None
    """Set for omission: the uncited principal code isolated on the base leg."""
    omitted_rule_id: str | None = None
    """Highest-ranked breached rule represented by ``omitted_code`` (diagnostic label)."""
    base_facts: FinancialFacts
    """Facts for this pair's base leg (not necessarily the submitted applicant)."""
    repaired_facts: FinancialFacts
    """Facts for this pair's counterfactual leg."""
    base_interventions: tuple[InterventionSpec, ...] = ()
    cf_interventions: tuple[InterventionSpec, ...] = ()

    @model_validator(mode="after")
    def _canonical_pair_identity(self) -> CounterfactualSpec:
        expected = pair_id_for(
            self.applicant_id,
            self.check,
            held_out_code=self.held_out_code,
            omitted_code=self.omitted_code,
            omitted_rule_id=self.omitted_rule_id,
            source_content_id=self.source_content_id,
            render_mode=self.render_mode,
            base_facts=self.base_facts,
            repaired_facts=self.repaired_facts,
        )
        if self.pair_id != expected:
            raise ValueError("CounterfactualSpec pair_id does not match its materialized contrast")
        return self

    @property
    def intervention_ids(self) -> tuple[str, ...]:
        """Ordered, de-duplicated intervention provenance for the complete contrast."""

        return tuple(
            dict.fromkeys(
                intervention.intervention_id
                for intervention in (*self.base_interventions, *self.cf_interventions)
            )
        )


def pair_id_for(
    applicant_id: str,
    check: str,
    *,
    held_out_code: ReasonCode | None = None,
    omitted_code: ReasonCode | None = None,
    omitted_rule_id: str | None = None,
    source_content_id: str,
    render_mode: RenderMode,
    base_facts: FinancialFacts | None = None,
    repaired_facts: FinancialFacts | None = None,
) -> str:
    return content_id(
        {
            "applicant_id": applicant_id,
            "check": check,
            "held_out_code": held_out_code.value if held_out_code else None,
            "omitted_code": omitted_code.value if omitted_code else None,
            "omitted_rule_id": omitted_rule_id,
            "source_content_id": source_content_id,
            "render_mode": render_mode,
            "base_facts": base_facts,
            "repaired_facts": repaired_facts,
        }
    )


def truly_breached_cited_codes(
    decision: GroundTruthDecision, cited: tuple[ReasonCode, ...]
) -> tuple[ReasonCode, ...]:
    """The subset of ``cited`` that the oracle actually breached -- excludes fabricated
    codes (``oracle.cited_not_breached``), preserving ``cited``'s original order."""
    fabricated = set(cited_not_breached(decision, cited))
    seen: list[ReasonCode] = []
    for code in cited:
        if code not in fabricated and code not in seen:
            seen.append(code)
    return tuple(seen)


def principal_breached_codes(
    decision: GroundTruthDecision, max_stated_reasons: int
) -> tuple[ReasonCode, ...]:
    """Ranked unique breached codes eligible to be principal stated reasons."""

    return decision.breached_codes[:max_stated_reasons]


def _repair_codes_sequentially(
    facts: FinancialFacts, codes: tuple[ReasonCode, ...], policy: Policy
) -> FinancialFacts:
    """Applies repair_code for each of ``codes`` in turn, re-evaluating the decision
    before each call so every call sees its own current, accurate breach set (repairing
    code A can shift what code B's rules see -- e.g. an income repair also moves DTI).

    Safe to apply sequentially across DIFFERENT codes (unlike Phase 4's documented hazard
    about repairing MULTIPLE RULES under ONE code, which needed extremal-merge): verified
    every pair of distinct ReasonCodes in this 16-rule policy targets disjoint fields,
    except BANKRUPTCY and DEROGATORY_PUBLIC_RECORD, which both touch ``public_records`` --
    but only ever by filtering out DISJOINT record kinds, and record-removal filtering is
    monotonic/idempotent regardless of application order (Phase 4's own repair.py notes
    this). policy/loader.py's A0 check separately guarantees no two rules under one code
    move a shared field in opposite directions; this function relies on that plus the
    cross-code disjointness just verified, not on reasoning about arbitrary policies."""
    for code in codes:
        decision = evaluate_against(facts, policy)
        facts = repair_code(facts, code, decision, policy)
    return facts


def _absolute_facts_interventions(
    *,
    applicant_id: str,
    pair_id: str,
    check: str,
    leg: str,
    original: FinancialFacts,
    target: FinancialFacts,
) -> tuple[InterventionSpec, ...]:
    """Describe one already-computed repaired arm as a registry-valid absolute update."""

    targets = {
        field: getattr(target, field)
        for field in FinancialFacts.model_fields
        if getattr(original, field) != getattr(target, field)
    }
    if not targets:
        return ()
    identity = {
        "applicant_id": applicant_id,
        "pair_id": pair_id,
        "check": check,
        "leg": leg,
        "targets": targets,
    }
    return (
        InterventionSpec(
            intervention_id=content_id(identity),
            family=Family.REASON_REPAIR,
            name=f"{check}:{leg}:absolute_facts",
            layer=Layer.FACTS,
            target_field=next(iter(targets)) if len(targets) == 1 else None,
            direction="set",
            expected_relation=Relation.FLIP_TO_APPROVE,
            params=FrozenDict({"targets": targets}),
        ),
    )


def _counterfactual_spec(
    *,
    pair_id: str,
    check: str,
    applicant_id: str,
    original_facts: FinancialFacts,
    base_facts: FinancialFacts,
    repaired_facts: FinancialFacts,
    held_out_code: ReasonCode | None = None,
    omitted_code: ReasonCode | None = None,
    omitted_rule_id: str | None = None,
    source_content_id: str,
    render_mode: RenderMode,
) -> CounterfactualSpec:
    return CounterfactualSpec(
        pair_id=pair_id,
        check=check,
        applicant_id=applicant_id,
        source_content_id=source_content_id,
        render_mode=render_mode,
        held_out_code=held_out_code,
        omitted_code=omitted_code,
        omitted_rule_id=omitted_rule_id,
        base_facts=base_facts,
        repaired_facts=repaired_facts,
        base_interventions=_absolute_facts_interventions(
            applicant_id=applicant_id,
            pair_id=pair_id,
            check=check,
            leg="base",
            original=original_facts,
            target=base_facts,
        ),
        cf_interventions=_absolute_facts_interventions(
            applicant_id=applicant_id,
            pair_id=pair_id,
            check=check,
            leg="counterfactual",
            original=original_facts,
            target=repaired_facts,
        ),
    )


def build_counterfactual_specs(
    applicant: Applicant,
    cited: tuple[ReasonCode, ...],
    decision: GroundTruthDecision,
    policy: Policy,
    *,
    render_mode: RenderMode,
) -> tuple[CounterfactualSpec, ...]:
    """Construct joint and isolated causal pairs for one submitted decision."""
    from credit_audit.ids import applicant_content_id

    applicant_id = applicant.applicant_id
    base_facts = applicant.facts
    source_content_id = applicant_content_id(applicant)
    truly_breached = truly_breached_cited_codes(decision, cited)
    all_real = decision.breached_codes
    principal = principal_breached_codes(decision, policy.process.max_stated_reasons)

    specs: list[CounterfactualSpec] = []

    joint_facts = _repair_codes_sequentially(base_facts, truly_breached, policy)
    if truly_breached:
        pair_id = pair_id_for(
            applicant_id,
            CHECK_JOINT_SUFFICIENCY,
            source_content_id=source_content_id,
            render_mode=render_mode,
            base_facts=base_facts,
            repaired_facts=joint_facts,
        )
        specs.append(
            _counterfactual_spec(
                pair_id=pair_id,
                check=CHECK_JOINT_SUFFICIENCY,
                applicant_id=applicant_id,
                original_facts=base_facts,
                base_facts=base_facts,
                repaired_facts=joint_facts,
                source_content_id=source_content_id,
                render_mode=render_mode,
            )
        )

    for held_out in truly_breached:
        others = tuple(code for code in all_real if code != held_out)
        only_reason_facts = _repair_codes_sequentially(base_facts, others, policy)
        full_repair_facts = _repair_codes_sequentially(only_reason_facts, (held_out,), policy)
        pair_id = pair_id_for(
            applicant_id,
            CHECK_NECESSITY_LOO,
            held_out_code=held_out,
            source_content_id=source_content_id,
            render_mode=render_mode,
            base_facts=only_reason_facts,
            repaired_facts=full_repair_facts,
        )
        specs.append(
            _counterfactual_spec(
                pair_id=pair_id,
                check=CHECK_NECESSITY_LOO,
                applicant_id=applicant_id,
                original_facts=base_facts,
                held_out_code=held_out,
                base_facts=only_reason_facts,
                repaired_facts=full_repair_facts,
                source_content_id=source_content_id,
                render_mode=render_mode,
            )
        )

    cited_set = set(cited)
    for omitted_code in principal:
        if omitted_code in cited_set:
            continue
        rule_eval = next(e for e in decision.breached_ranked if e.reason_code == omitted_code)
        others = tuple(code for code in all_real if code != omitted_code)
        only_reason_facts = _repair_codes_sequentially(base_facts, others, policy)
        full_repair_facts = _repair_codes_sequentially(only_reason_facts, (omitted_code,), policy)
        pair_id = pair_id_for(
            applicant_id,
            CHECK_OMISSION_SCAN,
            omitted_code=omitted_code,
            omitted_rule_id=rule_eval.rule_id,
            source_content_id=source_content_id,
            render_mode=render_mode,
            base_facts=only_reason_facts,
            repaired_facts=full_repair_facts,
        )
        specs.append(
            _counterfactual_spec(
                pair_id=pair_id,
                check=CHECK_OMISSION_SCAN,
                applicant_id=applicant_id,
                original_facts=base_facts,
                omitted_code=omitted_code,
                omitted_rule_id=rule_eval.rule_id,
                base_facts=only_reason_facts,
                repaired_facts=full_repair_facts,
                source_content_id=source_content_id,
                render_mode=render_mode,
            )
        )

    return tuple(specs)


def evaluate_against(facts: FinancialFacts, policy: Policy) -> GroundTruthDecision:
    """Small local re-evaluation helper -- repair_code needs each call's OWN current
    breach set (it repairs against whatever `decision` you pass it, not the applicant's
    original one), since after repairing code A, code B's breach set has generally
    changed (e.g. income repairs also move dti). Each construction loop above threads
    facts through repair_code sequentially and must re-evaluate before each call."""
    from credit_audit.policy.oracle import evaluate

    return evaluate(facts, policy)


__all__ = [
    "CHECK_FABRICATION",
    "CHECK_JOINT_SUFFICIENCY",
    "CHECK_NECESSITY_LOO",
    "CHECK_OMISSION_SCAN",
    "CounterfactualSpec",
    "build_counterfactual_specs",
    "pair_id_for",
    "principal_breached_codes",
    "truly_breached_cited_codes",
]
