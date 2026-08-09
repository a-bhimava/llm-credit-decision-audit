"""Core records for the audit harness.

Four invariants live here, and each is enforced by a test in ``tests/unit/test_types.py``
rather than by convention:

1. Money is ``int`` cents and ratios are ``Decimal`` quantized to 4dp. Never ``float`` for a
   financial quantity -- repairs do exact threshold arithmetic, and a float comparison against
   a 0.43 DTI threshold eventually produces a wrong repair. (Statistical quantities -- p-values,
   effect sizes, confidence -- are legitimately float and are exempt.)

2. :class:`FinancialFacts` stores primitives only. ``dti``, ``cltv`` and ``utilization`` are
   computed properties. This kills the bug class where repairing income leaves a stale DTI and
   hands the agent an incoherent record it can notice and react to.

3. :class:`Applicant` splits ``facts`` (everything the policy may consider) from
   ``presentation`` (name, employer, tone, ordering -- never scored). Every intervention
   declares which layer it touches via :attr:`InterventionSpec.layer`. This is what makes
   "identical financial profile, only the name changed" a structural guarantee rather than a
   claim we ask the reader to trust.

4. :attr:`TestResult.pair_id` is required. It is the bootstrap cluster identifier, so making it
   mandatory forces every check author to declare the clustering -- the mistake most evaluation
   repos make when they resample at the response level instead of the pair level.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RATIO_EXP = Decimal("0.0001")
"""Ratios are quantized to 4 decimal places. Policy thresholds are expressed at the same scale,
so comparisons are exact."""


def q4(value: Decimal) -> Decimal:
    """Quantize a ratio to 4dp, half-up. The single rounding rule for the whole codebase."""
    return value.quantize(RATIO_EXP, rounding=ROUND_HALF_UP)


class Frozen(BaseModel):
    """Immutable, extra-forbidding base. Every record in this module inherits it."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# --------------------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------------------


class DecisionOutcome(StrEnum):
    APPROVE = "APPROVE"
    DENY = "DENY"
    COUNTEROFFER = "COUNTEROFFER"
    REFER = "REFER"
    NO_DECISION = "NO_DECISION"


class ReasonCode(StrEnum):
    """Adverse-action reason vocabulary.

    Modelled on the Regulation B Appendix C sample notice plus standard credit-file codes. The
    per-code metadata table (repairable, target field, repair kind, severity) lands in
    ``reasons/codes.py`` in Phase 4; this enum is only the vocabulary.
    """

    INSUFFICIENT_INCOME = "INSUFFICIENT_INCOME"
    EXCESSIVE_OBLIGATIONS_DTI = "EXCESSIVE_OBLIGATIONS_DTI"
    INSUFFICIENT_CREDIT_HISTORY = "INSUFFICIENT_CREDIT_HISTORY"
    DELINQUENT_OBLIGATIONS = "DELINQUENT_OBLIGATIONS"
    DEROGATORY_PUBLIC_RECORD = "DEROGATORY_PUBLIC_RECORD"
    BANKRUPTCY = "BANKRUPTCY"
    CREDIT_SCORE_TOO_LOW = "CREDIT_SCORE_TOO_LOW"
    EXCESSIVE_UTILIZATION = "EXCESSIVE_UTILIZATION"
    TOO_MANY_INQUIRIES = "TOO_MANY_INQUIRIES"
    INSUFFICIENT_EMPLOYMENT_HISTORY = "INSUFFICIENT_EMPLOYMENT_HISTORY"
    TEMPORARY_OR_IRREGULAR_EMPLOYMENT = "TEMPORARY_OR_IRREGULAR_EMPLOYMENT"
    UNVERIFIABLE_INCOME = "UNVERIFIABLE_INCOME"
    COLLATERAL_VALUE_INSUFFICIENT = "COLLATERAL_VALUE_INSUFFICIENT"
    LOAN_AMOUNT_EXCEEDS_LIMIT = "LOAN_AMOUNT_EXCEEDS_LIMIT"
    INCOMPLETE_APPLICATION = "INCOMPLETE_APPLICATION"

    # Automatic failures -- these cost zero API calls.
    NON_SPECIFIC_INTERNAL_POLICY = "NON_SPECIFIC_INTERNAL_POLICY"
    """12 CFR 1002.9 official interpretation: "internal standards or policies" is insufficient
    on its face. Fails without any counterfactual being run."""

    PROHIBITED_BASIS_ADJACENT = "PROHIBITED_BASIS_ADJACENT"
    OUT_OF_SCHEMA_FACTOR = "OUT_OF_SCHEMA_FACTOR"
    """The agent cited a factor the applicant record cannot contain, so it cannot have scored
    it. A violation by construction, again with zero API calls."""

    OUT_OF_POLICY_FACTOR = "OUT_OF_POLICY_FACTOR"
    OTHER_UNMAPPED = "OTHER_UNMAPPED"


class EmploymentStatus(StrEnum):
    FULL_TIME = "FULL_TIME"
    PART_TIME = "PART_TIME"
    SELF_EMPLOYED = "SELF_EMPLOYED"
    CONTRACT = "CONTRACT"
    RETIRED = "RETIRED"
    UNEMPLOYED = "UNEMPLOYED"


class PublicRecordKind(StrEnum):
    BANKRUPTCY_CH7 = "BANKRUPTCY_CH7"
    BANKRUPTCY_CH13 = "BANKRUPTCY_CH13"
    TAX_LIEN = "TAX_LIEN"
    JUDGMENT = "JUDGMENT"
    COLLECTION = "COLLECTION"


class Family(StrEnum):
    """Intervention / test families. Must match the families declared in PREREGISTRATION.yaml;
    ``stats/families.py`` refuses to score a result whose family is not declared."""

    REASON_REPAIR = "REASON_REPAIR"
    MONOTONE = "MONOTONE"
    INVARIANCE = "INVARIANCE"
    SERIALIZATION = "SERIALIZATION"
    POLICY_ADHERENCE = "POLICY_ADHERENCE"
    DEMOGRAPHIC = "DEMOGRAPHIC"
    AUTHORITY = "AUTHORITY"
    FRAMING = "FRAMING"


class Relation(StrEnum):
    """What the intervention asserts about the decision."""

    NONDECREASING = "NONDECREASING"
    NONINCREASING = "NONINCREASING"
    INVARIANT = "INVARIANT"
    FLIP_TO_APPROVE = "FLIP_TO_APPROVE"
    UNCONSTRAINED = "UNCONSTRAINED"


class TestStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INAPPLICABLE = "inapplicable"
    ERROR = "error"


class Layer(StrEnum):
    """Which half of the applicant an intervention is permitted to touch. Enforced at apply
    time; see invariant 3."""

    FACTS = "facts"
    PRESENTATION = "presentation"


class MappingMethod(StrEnum):
    """How a free-text reason became a :class:`ReasonCode`. Always recorded, never inferred.

    ``llm_remap`` is the tier that would compromise the project's "judge-free" claim, so its
    rate is reported in every run rather than hidden.
    """

    STRUCTURED = "structured"
    LEXICON = "lexicon"
    EMBEDDING = "embedding"
    LLM_REMAP = "llm_remap"
    UNMAPPED = "unmapped"


class ParseStatus(StrEnum):
    STRUCTURED = "structured"
    REMAPPED = "remapped"
    HEURISTIC = "heuristic"
    UNPARSEABLE = "unparseable"


class Termination(StrEnum):
    SUBMITTED = "submitted"
    MAX_STEPS = "max_steps"
    MAX_TOKENS = "max_tokens"
    ERROR = "error"
    REFUSAL = "refusal"


class RenderMode(StrEnum):
    TABLE = "table"
    PROSE = "prose"
    JSON = "json"


# --------------------------------------------------------------------------------------
# Applicant
# --------------------------------------------------------------------------------------


class PublicRecord(Frozen):
    kind: PublicRecordKind
    months_ago: int = Field(ge=0)
    amount_cents: int = Field(ge=0)


class BankTxn(Frozen):
    day: int = Field(ge=1, le=31)
    description: str
    amount_cents: int
    """Signed: negative is a debit."""


class DemographicTags(Frozen):
    """Demographic signals attached to an applicant for the counterfactual bias arms.

    Never scored, never shown to the agent as labels -- they are realized only through
    ``Presentation.applicant_name`` and related surface features. Retained on the record so
    disparities can be estimated after the fact.

    These are synthetic. Framing note carried into every artifact: the bias arms are blindness
    / invariance tests under a stated causal assumption, not measurements of discrimination.
    """

    synthetic: Literal[True] = True
    race_ethnicity_signal: str | None = None
    sex_signal: str | None = None
    age_band_signal: str | None = None
    source: str = "synthetic"


class FinancialFacts(Frozen):
    """Everything the underwriting policy is permitted to consider.

    Primitives only -- see invariant 2. Derived quantities are properties below, so a repair
    that raises income automatically lowers DTI and the record stays internally coherent.
    """

    annual_income_cents: int = Field(ge=0)
    monthly_debt_cents: int = Field(ge=0)
    loan_amount_cents: int = Field(gt=0)
    property_value_cents: int = Field(ge=0)
    """0 for an unsecured product. ``cltv`` is then Decimal(0)."""
    loan_term_months: int = Field(gt=0)

    credit_score: int = Field(ge=300, le=850)
    open_tradelines: int = Field(ge=0)
    revolving_balance_cents: int = Field(ge=0)
    revolving_limit_cents: int = Field(ge=0)

    delinq_30d_24m: int = Field(ge=0)
    delinq_60d_24m: int = Field(ge=0)
    delinq_90p_24m: int = Field(ge=0)
    public_records: tuple[PublicRecord, ...] = ()

    oldest_tradeline_months: int = Field(ge=0)
    inquiries_6m: int = Field(ge=0)

    employment_months: int = Field(ge=0)
    employment_status: EmploymentStatus
    income_documented: bool

    # -- derived; NOT stored --------------------------------------------------------------

    @property
    def monthly_income_cents(self) -> int:
        return self.annual_income_cents // 12

    @property
    def dti(self) -> Decimal:
        """Debt-to-income. Returns Decimal(1) sentinel when income is zero, which every policy
        threshold treats as a breach."""
        income = self.monthly_income_cents
        if income <= 0:
            return q4(Decimal(1))
        return q4(Decimal(self.monthly_debt_cents) / Decimal(income))

    @property
    def cltv(self) -> Decimal:
        """Combined loan-to-value. Decimal(0) for unsecured products."""
        if self.property_value_cents <= 0:
            return q4(Decimal(0))
        return q4(Decimal(self.loan_amount_cents) / Decimal(self.property_value_cents))

    @property
    def utilization(self) -> Decimal:
        if self.revolving_limit_cents <= 0:
            return q4(Decimal(0))
        return q4(Decimal(self.revolving_balance_cents) / Decimal(self.revolving_limit_cents))

    @property
    def delinquencies_total(self) -> int:
        return self.delinq_30d_24m + self.delinq_60d_24m + self.delinq_90p_24m


class Presentation(Frozen):
    """Surface features the policy must NOT consider.

    Interventions in the DEMOGRAPHIC / AUTHORITY / FRAMING / INVARIANCE / SERIALIZATION
    families touch this layer and only this layer, leaving the ``facts`` hash bit-identical.
    """

    applicant_name: str
    employer_name: str
    employer_prestige_tier: int = Field(ge=1, le=5)
    """Authority arm. 1 = most prestigious. ICE-Guard (arXiv:2603.18530) measured authority
    bias in finance at 22.6% against demographic bias at 2.2%, so this arm carries more
    signal than the name swap."""
    school: str | None = None
    referral_note: str | None = None
    narrative_tone: Literal["neutral", "positive", "negative"] = "neutral"
    demographic_tags: DemographicTags = DemographicTags()
    bank_statement_lines: tuple[BankTxn, ...] = ()
    line_order_seed: int = 0
    """Invariance arm: permuting statement line order must not move the decision."""
    free_text_notes: tuple[str, ...] = ()


class Provenance(Frozen):
    generator_seed: int
    generator_version: str
    source_cell_id: str | None = None
    """Population cell the profile was drawn from. ``None`` for purely synthetic profiles."""
    parent_applicant_id: str | None = None
    intervention_lineage: tuple[str, ...] = ()
    """Ordered intervention_ids applied to reach this applicant from its base."""


class Applicant(Frozen):
    applicant_id: str
    facts: FinancialFacts
    presentation: Presentation
    provenance: Provenance


# --------------------------------------------------------------------------------------
# Decision
# --------------------------------------------------------------------------------------


class StatedReason(Frozen):
    rank: int = Field(ge=1)
    """Order is the principal-reason ranking; 1 is most important."""
    raw_text: str
    code: ReasonCode
    mapping_method: MappingMethod
    mapping_confidence: float = Field(ge=0.0, le=1.0)
    split_from: str | None = None
    """Set when one utterance yielded two codes ("high DTI and low income")."""
    span: tuple[int, int] | None = None
    """Character offsets into ``Decision.raw_text``, for the parse-highlight UI."""


class Decision(Frozen):
    outcome: DecisionOutcome
    apr_bps: int | None = None
    credit_limit_cents: int | None = None
    risk_grade: str | None = None
    stated_reasons: tuple[StatedReason, ...] = ()
    raw_text: str = ""
    parse_status: ParseStatus = ParseStatus.STRUCTURED
    is_adverse_action: bool = False
    """DENY, or COUNTEROFFER on terms worse than requested. Counteroffers count as adverse
    action under ECOA when the applicant does not accept, which is why the flag is separate
    from ``outcome``."""


# --------------------------------------------------------------------------------------
# Episode / trajectory
# --------------------------------------------------------------------------------------


class EpisodeKey(Frozen):
    applicant_id: str
    arm_id: str
    render_id: RenderMode
    trial_index: int = Field(ge=0)
    model_id: str
    prompt_hash: str
    seed: int


class Message(Frozen):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    step: int = Field(ge=0)


class ToolCall(Frozen):
    step: int = Field(ge=0)
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    ok: bool = True
    error: str | None = None
    latency_ms: int = Field(ge=0, default=0)


class Usage(Frozen):
    input_tokens: int = Field(ge=0, default=0)
    output_tokens: int = Field(ge=0, default=0)
    cached_tokens: int = Field(ge=0, default=0)
    """Read from the provider rather than assumed. The shared prompt prefix is ~1k tokens,
    below every published Gemini implicit-cache minimum, so cross-episode prefix caching does
    not fire -- what caches is within-episode accumulation. Measured, never asserted."""
    thought_tokens: int = Field(ge=0, default=0)
    cost_usd: float = Field(ge=0.0, default=0.0)
    cache_hit: bool = False
    replayed: bool = False


class Trajectory(Frozen):
    trajectory_id: str
    key: EpisodeKey
    messages: tuple[Message, ...] = ()
    tool_calls: tuple[ToolCall, ...] = ()
    final_state_hash: str = ""
    decision: Decision | None = None
    usage: Usage = Usage()
    termination: Termination = Termination.SUBMITTED


# --------------------------------------------------------------------------------------
# Interventions and results
# --------------------------------------------------------------------------------------


class InterventionSpec(Frozen):
    intervention_id: str
    family: Family
    name: str
    layer: Layer
    """Enforced at apply time: a FACTS intervention must leave the presentation hash
    bit-identical, and vice versa."""
    target_field: str | None = None
    direction: Literal["increase", "decrease", "set", "none"] = "none"
    expected_relation: Relation = Relation.UNCONSTRAINED
    params: dict[str, Any] = Field(default_factory=dict)


class TestResult(Frozen):
    test_id: str
    check: str
    """Dotted check identifier, e.g. ``reason_validity.necessity_loo``."""
    family: Family
    applicant_id: str
    intervention_ids: tuple[str, ...] = ()
    base_trajectory_ids: tuple[str, ...] = ()
    cf_trajectory_ids: tuple[str, ...] = ()
    status: TestStatus
    observed: dict[str, Any] = Field(default_factory=dict)
    expected: str = ""
    effect: float | None = None
    """approve_rate(cf) - approve_rate(base). Rate-based over k trials, never a single flip."""
    pair_id: str
    """Required. The bootstrap cluster identifier -- see invariant 4."""
    notes: str = ""


# --------------------------------------------------------------------------------------
# Run manifest
# --------------------------------------------------------------------------------------


class ModelSpec(Frozen):
    provider: str
    model_id: str
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    max_steps: int = 12
    system_prompt_hash: str = ""
    reason_mode: Literal["coded", "freetext"] = "coded"


class DatasetRef(Frozen):
    path: str
    sha256: str
    n: int = Field(ge=0)


class PolicyRef(Frozen):
    md_sha256: str
    yaml_sha256: str
    version: str


class PreregRef(Frozen):
    sha256: str
    git_tag: str | None = None
    frozen_at: datetime | None = None


class RunCounts(Frozen):
    planned: int = 0
    executed: int = 0
    cached: int = 0
    replayed: int = 0
    skipped: int = 0
    applicants: int = 0
    denied: int = 0
    tests: int = 0
    pairs: int = 0


class CostSummary(Frozen):
    usd_total: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cache_hit_rate: float | None = None


class RunManifest(Frozen):
    run_id: str
    created_at: datetime
    suite: str
    kind: Literal["scripted", "model"]
    """Drives the non-dismissible provenance banner on every route of the evidence site. A
    scripted run is a known-answer validation of the harness, not a finding about any model,
    and the exporter refuses to phrase it as one."""

    git_commit: str
    git_dirty: bool = False
    package_version: str = ""
    python_version: str = ""
    platform: str = ""

    model: ModelSpec
    seed: int
    profile_set: DatasetRef
    policy_ref: PolicyRef
    prereg_ref: PreregRef | None = None

    arms: tuple[str, ...] = ()
    renders: tuple[RenderMode, ...] = ()
    k_trials: int = Field(ge=1, default=5)
    """k=5 everywhere. The earlier two-stage screen-then-confirm design existed only as a cost
    control; at gemini-2.5-flash-lite prices a full run is ~$18, and dropping the two-stage
    design removes the upward bias that re-running only failures introduces."""

    counts: RunCounts = RunCounts()
    cost: CostSummary = CostSummary()
    artifacts: dict[str, str] = Field(default_factory=dict)


__all__ = [
    "RATIO_EXP",
    "Applicant",
    "BankTxn",
    "CostSummary",
    "DatasetRef",
    "Decision",
    "DecisionOutcome",
    "DemographicTags",
    "EmploymentStatus",
    "EpisodeKey",
    "Family",
    "FinancialFacts",
    "Frozen",
    "InterventionSpec",
    "Layer",
    "MappingMethod",
    "Message",
    "ModelSpec",
    "ParseStatus",
    "PolicyRef",
    "PreregRef",
    "Presentation",
    "Provenance",
    "PublicRecord",
    "PublicRecordKind",
    "ReasonCode",
    "Relation",
    "RenderMode",
    "RunCounts",
    "RunManifest",
    "StatedReason",
    "TestResult",
    "TestStatus",
    "Termination",
    "ToolCall",
    "Trajectory",
    "Usage",
    "q4",
]
