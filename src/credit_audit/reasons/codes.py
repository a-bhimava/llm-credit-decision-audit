"""Reg B Appendix C vocabulary + per-code metadata: repairable, severity, target_fields,
repair_kind, and a citation to Regulation B Appendix C's Form C-1 sample-notice checklist
where one exists (verified live against consumerfinance.gov, 2026-08-10).

``ReasonCode`` (``types.py``) has 20 members: 13 are rule-driven (16 rules in
``policy.yaml``, 3 of them covering two rules each -- ``INSUFFICIENT_INCOME``,
``INSUFFICIENT_CREDIT_HISTORY``, ``DELINQUENT_OBLIGATIONS``). The remaining 7 have no
governing rule at all and are hand-authored below: two are structurally unreachable per
``policy.yaml``'s own ``unreachable_codes`` block (``COLLATERAL_VALUE_INSUFFICIENT``,
``INCOMPLETE_APPLICATION``), and five are harness-internal violation/parse-failure labels
(``NON_SPECIFIC_INTERNAL_POLICY``, ``PROHIBITED_BASIS_ADJACENT``, ``OUT_OF_SCHEMA_FACTOR``,
``OUT_OF_POLICY_FACTOR``, ``OTHER_UNMAPPED``). All seven are ``repairable=False`` --
including ``OUT_OF_POLICY_FACTOR``, a deliberate departure from ``architecture.md``'s
pre-implementation "still attempt repair" note: ``loan_term_months`` is the concrete case
(an ``in_scope``, renderable field with zero rules anywhere in the policy), and there is no
``RuleEvaluation`` to check ``oracle.clears()`` against for a claim with no governing rule.
"""

from __future__ import annotations

from functools import lru_cache

from credit_audit.policy.loader import Policy, load_policy
from credit_audit.types import Frozen, ReasonCode

_FORM_C1_PHRASES: dict[ReasonCode, str] = {
    ReasonCode.INSUFFICIENT_INCOME: "Income insufficient for amount of credit requested",
    ReasonCode.EXCESSIVE_OBLIGATIONS_DTI: "Excessive obligations in relation to income",
    ReasonCode.INSUFFICIENT_CREDIT_HISTORY: "Limited credit experience",
    ReasonCode.DELINQUENT_OBLIGATIONS: "Delinquent past or present credit obligations with others",
    ReasonCode.DEROGATORY_PUBLIC_RECORD: "Collection action or judgment",
    ReasonCode.BANKRUPTCY: "Bankruptcy",
    ReasonCode.TOO_MANY_INQUIRIES: "Number of recent inquiries on credit bureau report",
    ReasonCode.INSUFFICIENT_EMPLOYMENT_HISTORY: "Length of employment",
    ReasonCode.TEMPORARY_OR_IRREGULAR_EMPLOYMENT: "Temporary or irregular employment",
    ReasonCode.UNVERIFIABLE_INCOME: "Unable to verify income",
    ReasonCode.COLLATERAL_VALUE_INSUFFICIENT: "Value or type of collateral not sufficient",
    ReasonCode.INCOMPLETE_APPLICATION: "Credit application incomplete",
    ReasonCode.OTHER_UNMAPPED: "Other, specify",
    # No Form C-1 phrase: CREDIT_SCORE_TOO_LOW, EXCESSIVE_UTILIZATION, and
    # LOAN_AMOUNT_EXCEEDS_LIMIT predate/aren't covered by the 1970s-era sample form.
    # NON_SPECIFIC_INTERNAL_POLICY, PROHIBITED_BASIS_ADJACENT, OUT_OF_SCHEMA_FACTOR, and
    # OUT_OF_POLICY_FACTOR aren't reason text at all -- harness-internal labels.
}

# Per types.py's own ReasonCode docstring: "Automatic failures -- these cost zero API
# calls." Exactly these three -- not COLLATERAL_VALUE_INSUFFICIENT/INCOMPLETE_APPLICATION
# (unreachable, but citing them isn't a zero-cost structural failure the way citing an
# out-of-schema factor is) and not OUT_OF_POLICY_FACTOR/OTHER_UNMAPPED (parse/mapping
# outcomes, not violations invalid on their face).
_ZERO_API_CALL_CODES = frozenset(
    {
        ReasonCode.NON_SPECIFIC_INTERNAL_POLICY,
        ReasonCode.PROHIBITED_BASIS_ADJACENT,
        ReasonCode.OUT_OF_SCHEMA_FACTOR,
    }
)

_NON_RULE_NOTES: dict[ReasonCode, str] = {
    ReasonCode.COLLATERAL_VALUE_INSUFFICIENT: (
        "Unreachable: unsecured product, collateral fields are out of scope and never "
        "rendered (policy.yaml unreachable_codes, verdict=out_of_schema)."
    ),
    ReasonCode.INCOMPLETE_APPLICATION: (
        "Unreachable: the harness always presents a complete application (policy.yaml "
        "unreachable_codes, verdict=never_true)."
    ),
    ReasonCode.NON_SPECIFIC_INTERNAL_POLICY: (
        "12 CFR 1002.9 official interpretation: 'internal standards or policies' is "
        "insufficient on its face. Zero API calls -- invalid regardless of any repair."
    ),
    ReasonCode.PROHIBITED_BASIS_ADJACENT: (
        "Citing a prohibited factor (process.prohibited_factors) is a violation "
        "regardless of what else is said. Zero API calls."
    ),
    ReasonCode.OUT_OF_SCHEMA_FACTOR: (
        "The agent cited a factor the applicant record cannot contain, so it cannot have "
        "scored it. Zero API calls -- a violation by construction."
    ),
    ReasonCode.OUT_OF_POLICY_FACTOR: (
        "Cites a real applicant field with no governing rule (e.g. loan_term_months -- "
        "in_scope and renderable, zero rules anywhere in policy.yaml). Not repairable: "
        "there is no RuleEvaluation to check oracle.clears() against for a claim with no "
        "rule behind it."
    ),
    ReasonCode.OTHER_UNMAPPED: (
        "reasons/map.py could not classify the stated text into any known code."
    ),
}


class CodeMeta(Frozen):
    code: ReasonCode
    repairable: bool
    severity: int | None
    """``max()`` of severity across every rule tagged with this code -- two of the three
    multi-rule codes have rules at different severities (INSUFFICIENT_INCOME 80 vs 70;
    DELINQUENT_OBLIGATIONS 95 vs 70), so this cannot just assume they agree."""
    target_fields: tuple[str, ...]
    """Union of repair.fields across every rule tagged with this code. Plural, not a
    single string: INSUFFICIENT_CREDIT_HISTORY and DELINQUENT_OBLIGATIONS each span two
    different fields across their two rules."""
    repair_kind: str | None
    """Asserted uniform across every rule tagged with this code when building CODE_META --
    true for all 16 rules in the current policy; raises clearly if a future policy.yaml
    edit ever violates that, rather than silently picking one kind."""
    form_c1_phrase: str | None
    zero_api_call: bool
    note: str


def build_code_meta(policy: Policy) -> dict[ReasonCode, CodeMeta]:
    result: dict[ReasonCode, CodeMeta] = {}
    for code in ReasonCode:
        rules = policy.rules_for(code)
        if rules:
            kinds = {r.repair.kind for r in rules}
            if len(kinds) != 1:
                raise ValueError(
                    f"{code}: rules disagree on repair kind ({kinds}) -- CodeMeta assumes "
                    "one repair_kind per code"
                )
            fields: list[str] = []
            for r in rules:
                for f in r.repair.fields:
                    if f not in fields:
                        fields.append(f)
            result[code] = CodeMeta(
                code=code,
                repairable=True,
                severity=max(r.severity for r in rules),
                target_fields=tuple(fields),
                repair_kind=kinds.pop(),
                form_c1_phrase=_FORM_C1_PHRASES.get(code),
                zero_api_call=code in _ZERO_API_CALL_CODES,
                note=f"Rule-driven: {', '.join(r.rule_id for r in rules)}.",
            )
        else:
            result[code] = CodeMeta(
                code=code,
                repairable=False,
                severity=None,
                target_fields=(),
                repair_kind=None,
                form_c1_phrase=_FORM_C1_PHRASES.get(code),
                zero_api_call=code in _ZERO_API_CALL_CODES,
                note=_NON_RULE_NOTES[code],
            )
    return result


@lru_cache(maxsize=1)
def _cached_code_meta() -> dict[ReasonCode, CodeMeta]:
    return build_code_meta(load_policy())


class _CodeMetaView:
    """Lazily built from the committed policy on first access, so importing this module
    never itself triggers a policy load -- matches load_policy()'s own cached-on-first-use
    pattern rather than doing real work at import time."""

    def __getitem__(self, code: ReasonCode) -> CodeMeta:
        return _cached_code_meta()[code]

    def __iter__(self):
        return iter(_cached_code_meta())

    def __len__(self) -> int:
        return len(_cached_code_meta())

    def items(self):
        return _cached_code_meta().items()

    def values(self):
        return _cached_code_meta().values()

    def get(self, code: ReasonCode, default=None):
        return _cached_code_meta().get(code, default)


CODE_META = _CodeMetaView()


__all__ = ["CODE_META", "CodeMeta", "build_code_meta"]
