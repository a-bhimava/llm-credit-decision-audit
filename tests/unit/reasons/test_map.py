"""map_reason: every rule's own statement text round-trips, prohibited/out-of-schema/
out-of-policy phrases map correctly, vague phrasing resolves last (not first), splitting
and re-merging work, and nonsense text falls through to UNMAPPED."""

from __future__ import annotations

from credit_audit.policy.loader import load_policy
from credit_audit.reasons.map import EMBEDDING_CONFIDENCE_FLOOR, _embedding_classify, map_reason
from credit_audit.types import MappingMethod, ReasonCode

RULE_DRIVEN_CODES = (
    ReasonCode.INSUFFICIENT_INCOME,
    ReasonCode.EXCESSIVE_OBLIGATIONS_DTI,
    ReasonCode.INSUFFICIENT_CREDIT_HISTORY,
    ReasonCode.DELINQUENT_OBLIGATIONS,
    ReasonCode.DEROGATORY_PUBLIC_RECORD,
    ReasonCode.BANKRUPTCY,
    ReasonCode.CREDIT_SCORE_TOO_LOW,
    ReasonCode.EXCESSIVE_UTILIZATION,
    ReasonCode.TOO_MANY_INQUIRIES,
    ReasonCode.INSUFFICIENT_EMPLOYMENT_HISTORY,
    ReasonCode.TEMPORARY_OR_IRREGULAR_EMPLOYMENT,
    ReasonCode.UNVERIFIABLE_INCOME,
    ReasonCode.LOAN_AMOUNT_EXCEEDS_LIMIT,
)


def test_every_rule_statement_maps_back_to_its_own_code():
    """Each rule-driven code's own policy.yaml statement text should resolve to that
    same code -- via lexicon or embedding, either is fine, but it must not be UNMAPPED."""
    policy = load_policy()
    for code in RULE_DRIVEN_CODES:
        for rule in policy.rules_for(code):
            clauses = map_reason(rule.statement, policy)
            assert clauses, f"{rule.rule_id}: statement produced no clauses"
            codes_seen = {c.code for c in clauses}
            assert code in codes_seen, (
                f"{rule.rule_id}'s own statement {rule.statement!r} did not map back to "
                f"{code}, got {codes_seen}"
            )


def test_prohibited_basis_text_maps_correctly():
    clauses = map_reason("Your race and national origin were considered.")
    assert all(c.code is ReasonCode.PROHIBITED_BASIS_ADJACENT for c in clauses)
    assert all(c.method is MappingMethod.LEXICON for c in clauses)


def test_out_of_schema_text_maps_correctly():
    clauses = map_reason("We reviewed your checking account balance and savings.")
    assert clauses
    assert all(c.code is ReasonCode.OUT_OF_SCHEMA_FACTOR for c in clauses)


def test_out_of_policy_factor_text_maps_correctly():
    """The concrete OUT_OF_POLICY_FACTOR case: loan_term_months has no governing rule."""
    clauses = map_reason("The requested term is too long for this product.")
    assert len(clauses) == 1
    assert clauses[0].code is ReasonCode.OUT_OF_POLICY_FACTOR
    assert clauses[0].method is MappingMethod.LEXICON


def test_collateral_text_maps_to_the_unreachable_code():
    clauses = map_reason("Insufficient collateral value for the requested loan amount.")
    assert len(clauses) == 1
    assert clauses[0].code is ReasonCode.COLLATERAL_VALUE_INSUFFICIENT


def test_vague_text_maps_to_non_specific_internal_policy():
    clauses = map_reason("This application does not meet our internal credit standards.")
    assert len(clauses) == 1
    assert clauses[0].code is ReasonCode.NON_SPECIFIC_INTERNAL_POLICY


def test_specific_pattern_wins_over_vague_catchall():
    """Adversarial case: contains 'meet our minimum' (which could trip a naive vague
    catch-all) but is unambiguously an income-insufficiency statement. The vague pattern
    must be checked LAST, only if nothing more specific matched."""
    clauses = map_reason("Income insufficient to meet our minimum lending criteria.")
    assert len(clauses) == 1
    assert clauses[0].code is ReasonCode.INSUFFICIENT_INCOME
    assert clauses[0].code is not ReasonCode.NON_SPECIFIC_INTERNAL_POLICY


def test_nonsense_text_falls_through_to_unmapped():
    clauses = map_reason("I have a bad feeling about this one.")
    assert len(clauses) == 1
    assert clauses[0].code is ReasonCode.OTHER_UNMAPPED
    assert clauses[0].method is MappingMethod.UNMAPPED
    assert clauses[0].confidence == 0.0


_LEXICON_AVOIDING_TEXT = (
    "tradelines reporting count applicant open two minimum twenty four months old "
    "oldest account age"
)
"""Shares vocabulary with min_open_tradelines/min_oldest_tradeline_months's statements
(enough for cosine similarity to clear the floor) without containing any literal
code_patterns phrase (verified: _lexicon_classify returns None for this exact string) --
the lexicon's vocabulary is deliberately comprehensive (seeded from the same rule
statements), which makes fully lexicon-avoiding, still-similar-enough text hard to find in
natural prose; this is closer to a token bag than a sentence for exactly that reason."""


def test_embedding_tier_scores_a_lexicon_avoiding_paraphrase_above_the_floor():
    code, score = _embedding_classify(_LEXICON_AVOIDING_TEXT, load_policy())
    assert code is ReasonCode.INSUFFICIENT_CREDIT_HISTORY
    assert score >= EMBEDDING_CONFIDENCE_FLOOR


def test_map_reason_uses_embedding_method_when_lexicon_does_not_match():
    """Same text through the full pipeline: no lexicon pattern matches, so mapping_method
    must be EMBEDDING (not LEXICON) even though the resolved code is the same."""
    clauses = map_reason(_LEXICON_AVOIDING_TEXT)
    assert len(clauses) == 1
    assert clauses[0].code is ReasonCode.INSUFFICIENT_CREDIT_HISTORY
    assert clauses[0].method is MappingMethod.EMBEDDING


def test_two_factor_sentence_splits_into_two_stated_reasons():
    clauses = map_reason("Insufficient income and excessive obligations in relation to income.")
    assert len(clauses) == 2
    codes = {c.code for c in clauses}
    assert codes == {ReasonCode.INSUFFICIENT_INCOME, ReasonCode.EXCESSIVE_OBLIGATIONS_DTI}
    assert all(c.split for c in clauses)


def test_adjacent_clauses_resolving_to_the_same_code_are_remerged():
    """One reason phrased as two sentence fragments must not become two StatedReasons."""
    clauses = map_reason(
        "Income insufficient; annual income does not meet the minimum required amount."
    )
    codes = [c.code for c in clauses]
    assert codes.count(ReasonCode.INSUFFICIENT_INCOME) == 1


def test_single_reason_is_not_marked_split():
    clauses = map_reason("Your credit score does not meet our minimum.")
    assert len(clauses) == 1
    assert clauses[0].split is False


def test_llm_remap_hook_is_never_used_when_not_provided():
    clauses = map_reason("completely unrecognizable gibberish text here")
    assert all(c.method is not MappingMethod.LLM_REMAP for c in clauses)


def test_llm_remap_hook_is_used_and_recorded_when_provided():
    """The hook exists for future wiring (no live LLM provider until Phase 9) but must
    never be silent about being used -- mapping_method records LLM_REMAP explicitly."""

    def fake_llm(_text: str) -> ReasonCode | None:
        return ReasonCode.CREDIT_SCORE_TOO_LOW

    clauses = map_reason("completely unrecognizable gibberish text here", llm_remap_fn=fake_llm)
    assert len(clauses) == 1
    assert clauses[0].code is ReasonCode.CREDIT_SCORE_TOO_LOW
    assert clauses[0].method is MappingMethod.LLM_REMAP


def test_empty_text_produces_no_clauses():
    assert map_reason("") == ()
    assert map_reason("   ") == ()
