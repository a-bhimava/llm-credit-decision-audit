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

4. :attr:`TestResult.pair_id` and ``cluster_id`` are required and distinct: the former names a
   contrast, while the latter names the originating experimental unit Phase 7 must resample.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    GetCoreSchemaHandler,
    model_serializer,
    model_validator,
)
from pydantic_core import core_schema

RATIO_EXP = Decimal("0.0001")
"""Ratios are quantized to 4 decimal places. Policy thresholds are expressed at the same scale,
so comparisons are exact."""

FIXED_DECIMAL_CTX = Context(prec=28)
"""The one Decimal context every ratio computation in this codebase runs under -- ``dti``,
``cltv``, ``utilization`` below, and ``policy/oracle.py``'s margin division. The ambient global
Decimal context can be mutated by any imported library (``decimal.getcontext().prec = 3``
makes a plain ``Decimal(1)/Decimal(3)`` raise ``InvalidOperation`` deep inside a comparison
that has nothing to do with whoever mutated it), and this project's whole export/verification
story depends on ratio arithmetic being byte-identical run to run. ``oracle.py`` imports this
same object rather than declaring its own, so there is exactly one fixed context, not two
independently-declared ones that happen to agree today and could silently drift apart."""


def q4(value: Decimal) -> Decimal:
    """Quantize a ratio to 4dp, half-up. The single rounding rule for the whole codebase."""
    with localcontext(FIXED_DECIMAL_CTX):
        return value.quantize(RATIO_EXP, rounding=ROUND_HALF_UP)


def freeze_json(value: Any) -> Any:
    """Recursively freeze a JSON-like value.

    Pydantic's ``frozen=True`` only prevents assigning model attributes.  Evidence payloads
    are commonly nested mappings and arrays, so leaving either mutable would let a cached
    policy, tool call, or test result change *after* its content ID had been computed.  This
    function is deliberately small and lossless for JSON-shaped data: mappings become
    :class:`FrozenDict`, arrays become tuples, and scalar values are returned unchanged.

    ``frozenset`` support is included for hashability of the occasional internal value even
    though provider/tool payloads themselves are JSON and therefore never contain sets.
    """
    if isinstance(value, FrozenDict):
        return value
    if isinstance(value, Mapping):
        return FrozenDict(value)
    if isinstance(value, tuple):
        return tuple(freeze_json(item) for item in value)
    if isinstance(value, list):
        return tuple(freeze_json(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(freeze_json(item) for item in value)
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    if value is None or isinstance(
        value,
        (bool, int, float, str, bytes, Decimal, date, datetime, StrEnum, Path),
    ):
        return value
    if isinstance(value, Frozen):
        return value
    raise TypeError(f"unsupported mutable or non-JSON payload type: {type(value).__name__}")


def thaw_json(value: Any) -> Any:
    """Return ordinary JSON containers for provider and JSON-Schema boundaries.

    The evidence model stays recursively immutable in memory.  Libraries such as
    ``jsonschema`` and provider SDKs sometimes insist on concrete ``dict``/``list`` values,
    so conversion happens explicitly at those boundaries rather than weakening the stored
    records.
    """
    if isinstance(value, Mapping):
        return {str(key): thaw_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [thaw_json(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [thaw_json(item) for item in sorted(value, key=repr)]
    return value


class FrozenDict(Mapping[str, Any]):
    """A recursively immutable and hashable mapping for evidence payloads.

    ``model_config = ConfigDict(frozen=True)`` only blocks *attribute reassignment*
    (``obj.field = x``); it does nothing to stop ``obj.field["key"] = x`` mutating a plain
    ``dict`` field's contents in place, and a plain ``dict`` is unhashable regardless. This
    class fixes both: pydantic validates a plain ``dict`` input into one of these
    transparently (see ``__get_pydantic_core_schema__``), and every read (``[]``, ``.get``,
    iteration, ``dict(x)``, ``**x``) works exactly like it did against the original ``dict``.

    Nested mappings and arrays are frozen on construction, so the whole value -- not only
    its outer shell -- is safe to content-address and hash.
    """

    __slots__ = ("_data",)

    def __init__(self, data: Mapping[str, Any] | None = None) -> None:
        object.__setattr__(
            self,
            "_data",
            {str(key): freeze_json(value) for key, value in data.items()} if data else {},
        )

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, FrozenDict):
            return self._data == other._data
        if isinstance(other, Mapping):
            return self._data == dict(other)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(frozenset(self._data.items()))

    def __repr__(self) -> str:
        return f"FrozenDict({self._data!r})"

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        dict_schema = core_schema.dict_schema(core_schema.str_schema(), core_schema.any_schema())
        return core_schema.no_info_after_validator_function(
            cls,
            dict_schema,
            serialization=core_schema.plain_serializer_function_ser_schema(thaw_json),
        )


class Frozen(BaseModel):
    """Immutable, extra-forbidding base. Every record in this module inherits it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_validator(mode="after")
    def _recursively_freeze_containers(self) -> Self:
        """Close the nested-container mutability hole for every frozen record.

        Several policy records predate :class:`FrozenDict` and retain ``dict`` annotations.
        Freezing centrally keeps those public annotations source-compatible while ensuring
        loaded/cached records cannot be mutated in place.
        """
        for name in type(self).model_fields:
            value = getattr(self, name)
            frozen = freeze_json(value)
            if frozen is not value:
                object.__setattr__(self, name, frozen)
        return self

    @model_serializer(mode="plain")
    def _serialize_frozen(self) -> dict[str, Any]:
        """Serialize legacy dict-annotated fields after their runtime deep-freeze.

        Pydantic compiles serializers from annotations, so a field annotated ``dict`` but
        sealed to ``FrozenDict`` after validation otherwise raises at export time.  Returning
        the record's public fields through ``thaw_json`` restores ordinary JSON containers;
        nested Pydantic records and scalar encoders remain handled by pydantic-core.
        """
        return {name: thaw_json(getattr(self, name)) for name in type(self).model_fields}

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        """Preserve recursive immutability across Pydantic's non-validating copy path."""
        copied = super().model_copy(update=update, deep=deep)
        return copied._recursively_freeze_containers()


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
    per-code metadata table (repairable, target field, repair kind, severity) lives in
    ``reasons/codes.py``; this enum is only the vocabulary.
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
    RENDER = "render"


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
    STOP = "stop"
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
        with localcontext(FIXED_DECIMAL_CTX):
            return q4(Decimal(self.monthly_debt_cents) / Decimal(income))

    @property
    def cltv(self) -> Decimal:
        """Combined loan-to-value. Decimal(0) for unsecured products."""
        if self.property_value_cents <= 0:
            return q4(Decimal(0))
        with localcontext(FIXED_DECIMAL_CTX):
            return q4(Decimal(self.loan_amount_cents) / Decimal(self.property_value_cents))

    @property
    def utilization(self) -> Decimal:
        if self.revolving_limit_cents <= 0:
            return q4(Decimal(0))
        with localcontext(FIXED_DECIMAL_CTX):
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
    """Synthetic authority-arm control label. 1 is the highest prestige tier.

    The tier itself is never rendered; provider-visible employer, school, and referral
    descriptors realize the intervention. Statistical significance is deliberately
    deferred to Phase 7.
    """
    school: str | None = None
    referral_note: str | None = None
    pronouns: str | None = None
    graduation_year: int | None = Field(default=None, ge=1900, le=2100)
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
    applicant_content_id: str
    arm_id: str
    render_id: RenderMode
    trial_index: int = Field(ge=0)
    model_id: str
    prompt_hash: str
    input_hash: str
    seed: int

    @property
    def episode_id(self) -> str:
        """Stable identity of the planned episode, independent of its realized trace."""
        # Local import avoids the intentional ids -> pydantic-types dependency pointing
        # back into this module at import time.
        from credit_audit.ids import content_id

        return content_id(self)


class RequestedToolCall(Frozen):
    """Provider-neutral assistant request retained verbatim in message history."""

    call_id: str = Field(min_length=1)
    name: str
    arguments: FrozenDict = Field(default_factory=FrozenDict)


class Message(Frozen):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    step: int = Field(ge=0)
    turn_index: int = Field(ge=0, default=0)
    tool_call_id: str | None = None
    tool_calls: tuple[RequestedToolCall, ...] = ()


class ToolCall(Frozen):
    call_id: str = Field(min_length=1)
    turn_index: int = Field(ge=0)
    step: int = Field(ge=0)
    name: str
    arguments: FrozenDict = Field(default_factory=FrozenDict)
    result: FrozenDict = Field(default_factory=FrozenDict)
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
    episode_id: str
    trajectory_id: str
    key: EpisodeKey
    messages: tuple[Message, ...] = ()
    tool_calls: tuple[ToolCall, ...] = ()
    final_state_hash: str = ""
    decision: Decision | None = None
    usage: Usage = Usage()
    termination: Termination = Termination.SUBMITTED

    provider_state: FrozenDict = Field(default_factory=FrozenDict)
    """Opaque provider continuation state observed during this episode.

    Persisted so a cassette is self-contained and a replay can reproduce the exact bytes a
    provider demanded back. Deliberately **outside** ``trajectory_content_id``, which takes
    its inputs explicitly: an encrypted provider token is not semantic history, and two runs
    that differ only in one must remain the same trajectory for comparison purposes.
    """

    @model_validator(mode="after")
    def _validate_content_identities(self) -> Trajectory:
        from credit_audit.ids import trajectory_content_id

        if self.episode_id != self.key.episode_id:
            raise ValueError("Trajectory episode_id does not match EpisodeKey")
        expected = trajectory_content_id(
            episode_id=self.episode_id,
            messages=self.messages,
            tool_calls=self.tool_calls,
            decision=self.decision,
            termination=self.termination,
        )
        if self.trajectory_id != expected:
            raise ValueError("Trajectory trajectory_id does not match semantic history")
        if self.termination is Termination.SUBMITTED and self.decision is None:
            raise ValueError("submitted Trajectory requires a decision")
        if self.termination is not Termination.SUBMITTED and self.decision is not None:
            raise ValueError("non-submitted Trajectory cannot carry a decision")

        requested: dict[str, RequestedToolCall] = {}
        for message in self.messages:
            for request in message.tool_calls:
                if message.role != "assistant":
                    raise ValueError("requested tool calls must belong to assistant messages")
                if request.call_id in requested:
                    raise ValueError("Trajectory contains a duplicate requested tool call_id")
                requested[request.call_id] = request
        calls: dict[str, ToolCall] = {}
        for call in self.tool_calls:
            if call.call_id in calls:
                raise ValueError("Trajectory contains a duplicate executed tool call_id")
            calls[call.call_id] = call
            request = requested.get(call.call_id)
            if request is None:
                raise ValueError("executed ToolCall lacks a correlated assistant request")
            if request.name != call.name or request.arguments != call.arguments:
                raise ValueError("executed ToolCall does not match its correlated request")
        tool_result_ids = {
            message.tool_call_id
            for message in self.messages
            if message.role == "tool" and message.tool_call_id is not None
        }
        if tool_result_ids != set(calls):
            raise ValueError("ToolCall records and correlated tool-result messages disagree")
        if self.termination is Termination.SUBMITTED and not any(
            call.name == "submit_decision" and call.ok for call in self.tool_calls
        ):
            raise ValueError("submitted Trajectory requires a successful submit_decision call")
        return self


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
    params: FrozenDict = Field(default_factory=FrozenDict)


class InterventionRecord(Frozen):
    """What one arm actually did to its applicant, persisted as run evidence.

    ``TestResult.intervention_ids`` keeps only the identifiers, flattened across both arms with
    no boundary between them, so the specs themselves used to vanish once an arm materialized.
    The pair viewer's whole job is showing which single field a contrast changed and why, and it
    cannot do that from a hash. Recorded here rather than reconstructed at export time: a
    re-derived intervention is the exporter's opinion about what happened, and everything else
    in this bundle is an observation of what happened.

    Indexed by the episode identities the arm produced, which is the only key that actually
    distinguishes arms. ``arm_id`` is reused across applicants, and ``(arm_id,
    applicant_content_id)`` is not unique either: on a leave-one-out necessity test every
    held-out choice for one applicant repairs to the *same* fully-repaired counterfactual, so
    several pairs share one cf applicant while having applied different repairs to reach it.
    """

    arm_id: str
    applicant_content_id: str
    episode_ids: tuple[str, ...] = ()
    interventions: tuple[InterventionSpec, ...] = ()


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
    observed: FrozenDict = Field(default_factory=FrozenDict)
    expected: str = ""
    effect: float | None = None
    """approve_rate(cf) - approve_rate(base). Rate-based over k trials, never a single flip."""
    pair_id: str
    """Required. Identifies one planned contrast and its matched trials."""
    cluster_id: str
    """Required. Identifies the originating experimental unit for Phase 7 resampling."""
    notes: str = ""

    @model_validator(mode="after")
    def _separate_contrast_and_cluster_identity(self) -> TestResult:
        if self.pair_id == self.cluster_id:
            raise ValueError("TestResult pair_id and cluster_id must be distinct")
        return self


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
    thought_tokens: int = 0
    cache_hits: int = 0
    replayed_responses: int = 0
    cache_hit_rate: float | None = None
    current_run_cost: bool = True
    """True when ``usd_total`` excludes replayed responses, which cost this run zero."""


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
    git_tag: str | None = None
    """The tag on the commit **the run executed at**, captured here rather than read live.

    The exporter used to call ``git describe`` at export time, which stapled whatever tag HEAD
    carried that day next to a commit from a different day. Re-exporting an unchanged run then
    produced different bytes, which is exactly the property the bundle claims not to have.
    """

    git_remote: str | None = None
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
    artifacts: FrozenDict = Field(default_factory=FrozenDict)


__all__ = [
    "FIXED_DECIMAL_CTX",
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
    "FrozenDict",
    "freeze_json",
    "InterventionRecord",
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
    "RequestedToolCall",
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
    "thaw_json",
]
