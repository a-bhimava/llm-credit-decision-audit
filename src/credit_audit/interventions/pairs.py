"""Pure construction of the counterfactual applicants Phase 5's reason-validity check needs
-- no execution, no model calls, no I/O. Given a base decision's cited reasons, this module
answers "what facts would I need to run this applicant against, to test each of the four
reason-validity checks?" `checks/reason_validity.py` is what actually runs those facts through
an episode and scores the result.

Four checks, four different construction rules -- see that module's own docstring for the
statistical/regulatory rationale. This module only cares about getting the FACTS right:

- **fabrication** needs no construction at all -- it's answerable directly from
  ``oracle.cited_not_breached`` against the base decision, no repaired facts required.
- **joint_sufficiency** repairs every cited code that was ACTUALLY breached, all at once.
- **necessity_loo**, per truly-breached cited code ``r_i``: repairs every OTHER
  truly-breached cited code except ``r_i``.
- **omission_scan**, per breached-but-uncited rule: repairs it ON TOP OF the
  joint-sufficiency-repaired facts (not on top of the original facts) -- verified against
  the real oracle during design that only this two-stage construction reproduces the
  documented expectation ("omission scan flags the missing one") when more than one real
  breach is simultaneously binding, which is the common, laundering-relevant case. A
  single-repair-alone construction never flips in that case, because the untouched breach
  independently blocks approval regardless of the omitted one.

Every ``pair_id`` is a deterministic hash of ``(applicant_id, check, construction
parameters)`` -- unique per (applicant, check, parameters), not per trial, since one
``TestResult`` bundles every k-trial base and counterfactual trajectory under one cluster
identifier for Phase 7's future cluster-bootstrap resampling.
"""

from __future__ import annotations

from credit_audit.ids import content_id
from credit_audit.interventions.repair import repair_code
from credit_audit.policy.loader import Policy
from credit_audit.policy.oracle import GroundTruthDecision, cited_not_breached, uncited_breaches
from credit_audit.types import FinancialFacts, Frozen, ReasonCode

CHECK_FABRICATION = "reason_validity.fabrication"
CHECK_JOINT_SUFFICIENCY = "reason_validity.joint_sufficiency"
CHECK_NECESSITY_LOO = "reason_validity.necessity_loo"
CHECK_OMISSION_SCAN = "reason_validity.omission_scan"


class CounterfactualSpec(Frozen):
    pair_id: str
    """Deterministic, unique per (applicant, check, construction parameters) -- see module
    docstring. The bootstrap cluster identifier this construction's TestResult will carry."""
    check: str
    applicant_id: str
    held_out_code: ReasonCode | None = None
    """Set only for necessity_loo: the cited-and-breached code that was NOT repaired."""
    omitted_rule_id: str | None = None
    """Set only for omission_scan: the breached-but-uncited rule additionally repaired on
    top of the joint-sufficiency-repaired facts."""
    repaired_facts: FinancialFacts


def pair_id_for(
    applicant_id: str,
    check: str,
    *,
    held_out_code: ReasonCode | None = None,
    omitted_rule_id: str | None = None,
) -> str:
    return content_id(
        {
            "applicant_id": applicant_id,
            "check": check,
            "held_out_code": held_out_code.value if held_out_code else None,
            "omitted_rule_id": omitted_rule_id,
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


def build_counterfactual_specs(
    applicant_id: str,
    base_facts: FinancialFacts,
    cited: tuple[ReasonCode, ...],
    decision: GroundTruthDecision,
    policy: Policy,
) -> tuple[CounterfactualSpec, ...]:
    """Construct every counterfactual applicant needed for joint_sufficiency, necessity_loo,
    and omission_scan against one applicant's cited reasons. Fabrication needs no
    construction (see module docstring) and isn't represented here -- it's computed
    directly from ``cited_not_breached(decision, cited)`` by the caller.

    joint_sufficiency/necessity_loo are omitted (there is nothing real to hold constant or
    leave out) when every cited code is fabricated -- but omission_scan is NOT skipped in
    that case: a cited set that's entirely fabricated can still coexist with a real,
    uncited breach (the ``credit_score=635`` LaunderingAgent fixture is exactly this: the
    only cited code, INSUFFICIENT_INCOME, was never breached, but CREDIT_SCORE_TOO_LOW
    was, uncited). ``joint_facts`` collapses to ``base_facts`` unchanged in that case
    (nothing real was cited to repair), which is exactly the base the omission scan should
    build its single-factor repairs on top of."""
    truly_breached = truly_breached_cited_codes(decision, cited)

    specs: list[CounterfactualSpec] = []

    joint_facts = _repair_codes_sequentially(base_facts, truly_breached, policy)
    if truly_breached:
        specs.append(
            CounterfactualSpec(
                pair_id=pair_id_for(applicant_id, CHECK_JOINT_SUFFICIENCY),
                check=CHECK_JOINT_SUFFICIENCY,
                applicant_id=applicant_id,
                repaired_facts=joint_facts,
            )
        )

    for held_out in truly_breached:
        others = tuple(c for c in truly_breached if c != held_out)
        loo_facts = _repair_codes_sequentially(base_facts, others, policy)
        specs.append(
            CounterfactualSpec(
                pair_id=pair_id_for(applicant_id, CHECK_NECESSITY_LOO, held_out_code=held_out),
                check=CHECK_NECESSITY_LOO,
                applicant_id=applicant_id,
                held_out_code=held_out,
                repaired_facts=loo_facts,
            )
        )

    # Two-stage by design (see module docstring Gap 2): built ON TOP OF joint_facts, not
    # base_facts. Repairing an omitted factor alone against the original facts would
    # never flip whenever another cited-but-unrepaired breach independently blocks
    # approval -- verified against the real oracle during design.
    for rule_eval in uncited_breaches(decision, cited):
        omission_facts = repair_code(
            joint_facts, rule_eval.reason_code, evaluate_against(joint_facts, policy), policy
        )
        specs.append(
            CounterfactualSpec(
                pair_id=pair_id_for(
                    applicant_id, CHECK_OMISSION_SCAN, omitted_rule_id=rule_eval.rule_id
                ),
                check=CHECK_OMISSION_SCAN,
                applicant_id=applicant_id,
                omitted_rule_id=rule_eval.rule_id,
                repaired_facts=omission_facts,
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
    "truly_breached_cited_codes",
]
