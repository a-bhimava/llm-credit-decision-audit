"""Freetext reason -> ``ReasonCode`` mapping. The thing Phase 2's
``env/tools.py::_parse_submit_decision`` freetext branch always deferred: *"Freetext ->
code mapping is Phase 4's job."*

Three tiers, in order, ``mapping_method`` always recorded on the result -- never inferred
after the fact:

1. **LEXICON** -- regex/keyword match against :mod:`reasons/lexicon.yaml`, itself seeded
   from ``policy.yaml``'s own alias lists so this vocabulary can't independently drift from
   what the policy actually declares in/out of scope. Checked in three ordered passes:
   prohibited-basis/out-of-schema/collateral patterns first (citing a forbidden or
   nonexistent factor is a violation regardless of what else is said), then specific
   rule-driven ``code_patterns`` (in the declared priority order -- e.g. "bankruptcy"
   before the more general public-record patterns), then the vague
   ``NON_SPECIFIC_INTERNAL_POLICY`` catch-all LAST, only if nothing more specific matched.
   A catch-all checked first would misclassify a specific sentence like *"Income
   insufficient to meet our minimum lending criteria"* just because it contains "meet our
   minimum."
2. **EMBEDDING** -- a lightweight LOCAL heuristic, not a real neural embedding model:
   ``collections.Counter`` token-overlap cosine similarity against each rule-driven code's
   own ``statement:`` text plus its Form C-1 phrase (``reasons/codes.py``). Confidence is
   the similarity score; below :data:`EMBEDDING_CONFIDENCE_FLOOR` the result is
   ``UNMAPPED``. Zero new dependencies -- ~20 short reference phrases don't need a real
   embedding model, and none is wired into this project until Phase 9.
3. **LLM_REMAP** -- not implemented this phase (no live LLM provider exists until Phase 9).
   ``map_reason`` accepts an optional ``llm_remap_fn`` hook, always ``None`` today. Per
   ``MappingMethod``'s own docstring this tier "would compromise the project's judge-free
   claim" if it were ever silent, so it stays entirely absent rather than half-built.

One utterance can yield more than one code (``StatedReason.split_from``): raw text is split
on conjunctions/delimiters into clauses, each mapped independently, then adjacent clauses
that resolve to the SAME code are re-merged -- avoiding spurious duplicate ``StatedReason``s
from one reason phrased as two sentence fragments.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from credit_audit.policy.loader import Policy, load_policy
from credit_audit.reasons.codes import CODE_META
from credit_audit.types import Frozen, MappingMethod, ReasonCode

LEXICON_PATH = Path(__file__).parent / "lexicon.yaml"

EMBEDDING_CONFIDENCE_FLOOR = 0.35

_SPLIT_RE = re.compile(r"\s*(?:;|\n|(?<=[a-z])\s+and\s+(?=[A-Za-z]))\s*")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


class MappedClause(Frozen):
    text: str
    code: ReasonCode
    method: MappingMethod
    confidence: float
    split: bool
    """True if this clause came from splitting a longer raw_text into multiple pieces."""


LlmRemapFn = Callable[[str], ReasonCode | None]


@lru_cache(maxsize=1)
def _load_lexicon() -> dict[str, Any]:
    return yaml.safe_load(LEXICON_PATH.read_text())


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _cosine_similarity(a: Counter, b: Counter) -> float:
    common = set(a) & set(b)
    numerator = sum(a[t] * b[t] for t in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return numerator / (norm_a * norm_b)


_REFERENCE_VECTOR_CACHE: dict[str, tuple[tuple[ReasonCode, Counter], ...]] = {}


def _reference_vectors(policy: Policy) -> tuple[tuple[ReasonCode, Counter], ...]:
    """One token-count vector per repairable rule-driven code, built from that code's
    rule statement(s) plus its Form C-1 phrase (if any). Cached by ``policy.yaml_sha256``
    (a hashable string) rather than the ``Policy`` object itself: ``Policy`` has a plain
    ``dict`` field (``fields``) and is not hashable, so it cannot be an ``lru_cache`` key
    directly -- a manual dict keyed by the content hash sidesteps that without needing
    Policy itself to change."""
    cached = _REFERENCE_VECTOR_CACHE.get(policy.yaml_sha256)
    if cached is not None:
        return cached

    vectors = []
    for code, meta in CODE_META.items():
        rules = policy.rules_for(code)
        if not rules:
            continue
        text = " ".join(r.statement for r in rules)
        if meta.form_c1_phrase:
            text += " " + meta.form_c1_phrase
        vectors.append((code, Counter(_tokenize(text))))
    result = tuple(vectors)
    _REFERENCE_VECTOR_CACHE[policy.yaml_sha256] = result
    return result


def _split(raw_text: str) -> list[str]:
    parts = [p.strip() for p in _SPLIT_RE.split(raw_text)]
    return [p for p in parts if p]


def _contains_pattern(text_lower: str, patterns: list[str]) -> bool:
    return any(pattern in text_lower for pattern in patterns)


def _lexicon_classify(text: str, lexicon: dict[str, Any]) -> ReasonCode | None:
    text_lower = text.lower()

    if _contains_pattern(text_lower, lexicon["prohibited_basis_patterns"]):
        return ReasonCode.PROHIBITED_BASIS_ADJACENT
    if _contains_pattern(text_lower, lexicon["collateral_patterns"]):
        return ReasonCode.COLLATERAL_VALUE_INSUFFICIENT
    if _contains_pattern(text_lower, lexicon["out_of_schema_patterns"]):
        return ReasonCode.OUT_OF_SCHEMA_FACTOR
    if _contains_pattern(text_lower, lexicon["out_of_policy_patterns"]):
        return ReasonCode.OUT_OF_POLICY_FACTOR

    for entry in lexicon["code_patterns"]:
        if _contains_pattern(text_lower, entry["patterns"]):
            return ReasonCode(entry["code"])

    if _contains_pattern(text_lower, lexicon["vague_patterns"]):
        return ReasonCode.NON_SPECIFIC_INTERNAL_POLICY

    return None


def _embedding_classify(text: str, policy: Policy) -> tuple[ReasonCode | None, float]:
    tokens = Counter(_tokenize(text))
    if not tokens:
        return None, 0.0
    best_code: ReasonCode | None = None
    best_score = 0.0
    for code, reference in _reference_vectors(policy):
        score = _cosine_similarity(tokens, reference)
        if score > best_score:
            best_score = score
            best_code = code
    if best_code is not None and best_score >= EMBEDDING_CONFIDENCE_FLOOR:
        return best_code, best_score
    return None, best_score


def _classify_clause(
    text: str, policy: Policy, lexicon: dict[str, Any], llm_remap_fn: LlmRemapFn | None
) -> tuple[ReasonCode, MappingMethod, float]:
    lexicon_code = _lexicon_classify(text, lexicon)
    if lexicon_code is not None:
        return lexicon_code, MappingMethod.LEXICON, 1.0

    embedding_code, score = _embedding_classify(text, policy)
    if embedding_code is not None:
        return embedding_code, MappingMethod.EMBEDDING, score

    if llm_remap_fn is not None:
        remapped = llm_remap_fn(text)
        if remapped is not None:
            return remapped, MappingMethod.LLM_REMAP, 1.0

    return ReasonCode.OTHER_UNMAPPED, MappingMethod.UNMAPPED, 0.0


def map_reason(
    raw_text: str,
    policy: Policy | None = None,
    *,
    llm_remap_fn: LlmRemapFn | None = None,
) -> tuple[MappedClause, ...]:
    policy = policy or load_policy()
    lexicon = _load_lexicon()

    clause_texts = _split(raw_text)
    if not clause_texts:
        return ()

    is_split = len(clause_texts) > 1
    raw_clauses: list[MappedClause] = []
    for text in clause_texts:
        code, method, confidence = _classify_clause(text, policy, lexicon, llm_remap_fn)
        raw_clauses.append(
            MappedClause(text=text, code=code, method=method, confidence=confidence, split=is_split)
        )

    return _remerge(raw_clauses)


def _remerge(clauses: list[MappedClause]) -> tuple[MappedClause, ...]:
    """Adjacent clauses resolving to the SAME code are one reason, not two -- e.g. "the
    applicant's income is insufficient and their annual income does not meet the minimum"
    is one INSUFFICIENT_INCOME reason phrased twice, not two separate reasons."""
    if len(clauses) <= 1:
        return tuple(clauses)

    merged: list[MappedClause] = [clauses[0]]
    for clause in clauses[1:]:
        prior = merged[-1]
        if clause.code == prior.code:
            merged[-1] = prior.model_copy(
                update={
                    "text": f"{prior.text}; {clause.text}",
                    "confidence": min(prior.confidence, clause.confidence),
                }
            )
        else:
            merged.append(clause)
    return tuple(merged)


__all__ = [
    "EMBEDDING_CONFIDENCE_FLOOR",
    "LlmRemapFn",
    "MappedClause",
    "map_reason",
]
