"""Lexicon sanity: no ambiguous cross-code collisions on canonical phrases, and the
committed lexicon.yaml has the shape map.py expects."""

from __future__ import annotations

from credit_audit.reasons.map import _load_lexicon
from credit_audit.types import ReasonCode


def test_lexicon_has_expected_sections():
    lexicon = _load_lexicon()
    for key in (
        "prohibited_basis_patterns",
        "out_of_schema_patterns",
        "out_of_policy_patterns",
        "collateral_patterns",
        "vague_patterns",
        "code_patterns",
    ):
        assert key in lexicon, f"lexicon.yaml missing {key!r}"


def test_code_patterns_reference_only_real_reason_codes():
    lexicon = _load_lexicon()
    for entry in lexicon["code_patterns"]:
        ReasonCode(entry["code"])  # raises if not a real code
        assert entry["patterns"], f"{entry['code']} has no patterns"


def test_no_pattern_appears_under_two_different_codes():
    """Every specific pattern string should belong to exactly one code_patterns entry --
    duplication would make match order do silent, undocumented work."""
    lexicon = _load_lexicon()
    seen: dict[str, str] = {}
    for entry in lexicon["code_patterns"]:
        for pattern in entry["patterns"]:
            assert pattern not in seen, (
                f"pattern {pattern!r} appears under both {seen.get(pattern)} and {entry['code']}"
            )
            seen[pattern] = entry["code"]


def test_bankruptcy_is_checked_before_the_more_general_public_record_patterns():
    """bankruptcy is more specific than the general public-record patterns and both
    codes cover overlapping subject matter -- BANKRUPTCY must come first in code_patterns
    so 'bankruptcy filing' resolves to BANKRUPTCY, not DEROGATORY_PUBLIC_RECORD."""
    lexicon = _load_lexicon()
    codes_in_order = [entry["code"] for entry in lexicon["code_patterns"]]
    assert codes_in_order.index("BANKRUPTCY") < codes_in_order.index("DEROGATORY_PUBLIC_RECORD")
