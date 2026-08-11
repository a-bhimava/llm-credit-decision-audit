"""Load, validate, and hash the underwriting policy.

`policy.md` is the document the agent reads. `policy.yaml` is the document the oracle
enforces. If they disagree, every reason-validity result in the project becomes garbage
while every downstream test stays green -- so this module's job is to make that
disagreement structurally impossible rather than merely unlikely.

Five assertions run on every cache miss inside :func:`load_policy` -- the first call in a
process, or any call after :func:`load_policy.cache_clear`, not only in CI. Subsequent calls
in the same process reuse the cached, already-validated :class:`Policy` (``evaluate()`` runs
this hot); re-validating on every call would re-read and re-check an unchanged committed
file for no added safety, since nothing mutates it between calls in one process:

  A0  YAML self-consistency: rule ids unique, codes real, accessors resolve, repair
      fields are FinancialFacts primitives (never properties), no code's rules move the
      same field in opposite directions, no rule uses an unreachable code.
  A1  Structural: every declared generated block exists exactly once in policy.md, and
      its body byte-equals what render_generated_block() produces from policy.yaml.
  A2  Referential: every rule's anchor resolves to a heading in policy.md.
  A3  Numeric lint: every number in policy.md's HAND-WRITTEN regions is either a
      rendering of a declared value or explicitly allowlisted.
  A4  Registry completeness: every FinancialFacts field is classified in policy.yaml,
      and every Presentation field is listed as a prohibited factor -- enforcing the
      facts/presentation split (see types.py) at the policy layer, not only the type
      layer.

A consistency check that has never been observed to fail is not a gate. The test suite
mutates the committed files one at a time and asserts each assertion actually raises.
"""

from __future__ import annotations

import difflib
import re
from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field

from credit_audit.ids import sha256_file
from credit_audit.types import (
    FinancialFacts as _FinancialFacts,
)
from credit_audit.types import (
    Frozen,
    Presentation,
    PublicRecordKind,
    ReasonCode,
)

POLICY_DIR = Path(__file__).parent
MD_PATH = POLICY_DIR / "policy.md"
YAML_PATH = POLICY_DIR / "policy.yaml"

_NUMBER_RE = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?%?")
_HEADING_RE = re.compile(r"^(?P<level>#{2,3})\s+(?P<anchor>\d+(?:\.\d+)?)\s+(?P<title>.+?)\s*$")
_XREF_RE = re.compile(r"§\s?(\d+(?:\.\d+)?)")
_BEGIN_RE = re.compile(r"<!--\s*BEGIN GENERATED policy\.yaml:(?P<id>[a-z_]+)\s*-->")
_END_RE = re.compile(r"<!--\s*END GENERATED policy\.yaml:(?P<id>[a-z_]+)\s*-->")


class PolicyError(Exception):
    """Base for every policy loading/validation failure."""


class PolicySchemaError(PolicyError):
    """policy.yaml does not conform to the source schema this loader expects."""


class PolicyFloatError(PolicyError):
    """A float was found somewhere in the parsed policy.yaml document.

    Every numeric value in policy.yaml must be a quoted string so it parses as an exact
    Decimal, never a native float. This is a second, independent defense on top of the
    quoting convention -- a defense-in-depth measure, because the convention alone relies
    on every contributor remembering to quote every number, forever.
    """


class PolicyDivergenceError(PolicyError):
    """policy.md's generated content does not match what policy.yaml renders.

    Carries a unified diff and the literal fix command in its message.
    """


class PolicyProseNumberError(PolicyError):
    """A numeral in policy.md's hand-written prose is not traceable to policy.yaml."""


class PolicyReferenceError(PolicyError):
    """A rule anchor or a section cross-reference does not resolve."""


class PolicyRegistryError(PolicyError):
    """The field/factor registry does not exactly cover FinancialFacts / Presentation."""


# --------------------------------------------------------------------------------------
# Float guard
# --------------------------------------------------------------------------------------


def reject_floats(obj: Any, path: str = "$") -> None:
    """Raise :class:`PolicyFloatError` if a native float appears anywhere in ``obj``.

    Runs immediately after ``yaml.safe_load``, before any other processing, so a stray
    unquoted number is caught at the earliest possible point rather than surfacing later
    as a subtly wrong comparison.
    """
    if isinstance(obj, float):
        raise PolicyFloatError(
            f"{path}: unquoted float {obj!r} in policy.yaml -- quote it as a string"
        )
    if isinstance(obj, dict):
        for key, value in obj.items():
            reject_floats(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            reject_floats(value, f"{path}[{index}]")


# --------------------------------------------------------------------------------------
# Source-side records (parsed policy.yaml)
# --------------------------------------------------------------------------------------


class PredicateKind(StrEnum):
    NUMERIC_MIN = "numeric_min"
    NUMERIC_MAX = "numeric_max"
    FLAG_TRUE = "flag_true"
    ENUM_ALLOWED = "enum_allowed"


class AccessorKind(StrEnum):
    PRIMITIVE = "primitive"
    PROPERTY = "property"
    DERIVED = "derived"


class MarginKind(StrEnum):
    CONTINUOUS = "continuous"
    ORDINAL = "ordinal"
    BINARY = "binary"


class Accessor(Frozen):
    kind: AccessorKind
    field: str | None = None
    name: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class RepairSpecHint(Frozen):
    kind: Literal["threshold_cross", "record_remove", "flag_set", "enum_set", "count_reduce"]
    fields: tuple[str, ...]
    direction: Literal["increase", "decrease", "set"]
    params: dict[str, Any] = Field(default_factory=dict)


class Rule(Frozen):
    rule_id: str
    section: str
    anchor: str
    predicate: PredicateKind
    accessor: Accessor
    threshold: Decimal | None = None
    allowed: tuple[str, ...] = ()
    display_value: str
    reason_code: ReasonCode
    margin_unit: Decimal
    margin_kind: MarginKind
    boundary_stratify: bool = True
    severity: int
    statement: str
    repair: RepairSpecHint


class FieldSpec(Frozen):
    name: str
    kind: AccessorKind
    type: str
    in_scope: bool = True
    renderable: bool = True
    informational: bool = False
    display: str = ""
    aliases: tuple[str, ...] = ()
    plausible_range: tuple[str, str] | None = None
    out_of_scope_reason: str | None = None


class ProhibitedFactor(Frozen):
    factor: str
    basis: Literal["reg_b", "presentation_layer"]
    aliases: tuple[str, ...] = ()


class ProcessPolicy(Frozen):
    decision_tool: str
    required_tools_before_decision: tuple[str, ...]
    required_tools_before_code: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    prohibited_tools: tuple[str, ...]
    prohibited_factors: tuple[ProhibitedFactor, ...]
    max_stated_reasons: int
    min_stated_reasons_on_adverse_action: int
    max_steps: int


class ProductSpec(Frozen):
    name: str
    kind: str
    secured: bool
    synthetic: Literal[True] = True
    min_amount_cents: int
    max_amount_cents: int
    min_term_months: int
    max_term_months: int


class UnreachableCode(Frozen):
    code: ReasonCode
    verdict: Literal["out_of_schema", "never_true"]
    note: str


class OutOfSchemaConcept(Frozen):
    concept: str
    aliases: tuple[str, ...] = ()


class PolicySection(Frozen):
    anchor: str
    title: str
    level: int
    start: int
    end: int


class PolicyDoc(Frozen):
    text: str
    sections: tuple[PolicySection, ...]


class Policy(Frozen):
    version: str
    product: ProductSpec
    fields: dict[str, FieldSpec]
    rules: tuple[Rule, ...]
    unreachable_codes: tuple[UnreachableCode, ...]
    out_of_schema_concepts: tuple[OutOfSchemaConcept, ...]
    process: ProcessPolicy
    prose_numeric_allowlist: tuple[str, ...]
    doc: PolicyDoc
    md_sha256: str
    yaml_sha256: str

    def rule(self, rule_id: str) -> Rule:
        for rule in self.rules:
            if rule.rule_id == rule_id:
                return rule
        raise KeyError(rule_id)

    def rules_for(self, code: ReasonCode) -> tuple[Rule, ...]:
        return tuple(r for r in self.rules if r.reason_code == code)

    def field(self, name: str) -> FieldSpec:
        return self.fields[name]

    @property
    def renderable_fields(self) -> tuple[FieldSpec, ...]:
        """Fields the agent may be shown. Phase 3's renderers must draw only from this
        set -- if a table render iterated FinancialFacts.model_fields directly instead,
        it would show the agent `Property value: $0` and the zero-API-call
        OUT_OF_SCHEMA_FACTOR finding on "insufficient collateral" would become
        indefensible, since the agent would have actually been shown the field."""
        return tuple(f for f in self.fields.values() if f.renderable and f.kind != "derived")


# --------------------------------------------------------------------------------------
# YAML -> Policy (pre-hash construction, before doc parsing)
# --------------------------------------------------------------------------------------


def _dec(value: Any) -> Decimal:
    if not isinstance(value, str):
        raise PolicySchemaError(f"expected a quoted numeric string, got {value!r}")
    return Decimal(value)


def _parse_accessor(raw: dict[str, Any]) -> Accessor:
    return Accessor(
        kind=AccessorKind(raw["kind"]),
        field=raw.get("field"),
        name=raw.get("name"),
        params=raw.get("params", {}) or {},
    )


def _parse_repair(raw: dict[str, Any]) -> RepairSpecHint:
    return RepairSpecHint(
        kind=raw["kind"],
        fields=tuple(raw["fields"]),
        direction=raw["direction"],
        params=raw.get("params", {}) or {},
    )


def _derive_display_value(threshold: Decimal, value_kind: str) -> str:
    """Compute display_value FROM threshold, rather than trusting a hand-typed YAML
    string. A hand-typed display_value can silently drift from threshold -- exactly the
    class of bug this module exists to prevent, and it is not hypothetical: it is what
    the first version of this file did, and a mutation test caught it (see
    test_mutated_yaml_threshold_raises_divergence).
    """
    if value_kind == "percent":
        pct = threshold * 100
        return f"{pct.normalize():f}%" if pct == pct.to_integral() else f"{pct}%"
    if value_kind == "currency_cents":
        return format_value("int_cents", int(threshold))
    if value_kind == "months":
        return f"{int(threshold)} months"
    if value_kind in ("count", "score"):
        return str(int(threshold))
    raise PolicySchemaError(f"unknown value_kind: {value_kind!r}")


def _parse_rule(raw: dict[str, Any]) -> Rule:
    threshold = _dec(raw["threshold"]) if "threshold" in raw else None
    if "value_kind" in raw:
        # Numeric rules: display_value is DERIVED, never hand-typed, so it cannot drift
        # from threshold. Reject an accidental hand-typed display_value alongside it --
        # having both would silently reintroduce the two-representations-of-one-number
        # problem this function exists to close.
        if "display_value" in raw:
            raise PolicySchemaError(
                f"{raw['rule_id']}: rule declares both value_kind and display_value; "
                "display_value must be derived from threshold via value_kind, not "
                "hand-typed alongside it"
            )
        display_value = _derive_display_value(threshold, raw["value_kind"])
    else:
        # Binary rules (flag_true / enum_allowed) have no single numeric threshold to
        # derive a display string from, so display_value is hand-typed for these only.
        display_value = str(raw["display_value"])

    return Rule(
        rule_id=raw["rule_id"],
        section=str(raw["section"]),
        anchor=str(raw["anchor"]),
        predicate=PredicateKind(raw["predicate"]),
        accessor=_parse_accessor(raw["accessor"]),
        threshold=threshold,
        allowed=tuple(raw.get("allowed", ())),
        display_value=display_value,
        reason_code=ReasonCode(raw["reason_code"]),
        margin_unit=_dec(raw["margin_unit"]),
        margin_kind=MarginKind(raw["margin_kind"]),
        boundary_stratify=bool(raw.get("boundary_stratify", True)),
        severity=int(raw["severity"]),
        statement=" ".join(raw["statement"].split()),
        repair=_parse_repair(raw["repair"]),
    )


def _parse_field(name: str, raw: dict[str, Any]) -> FieldSpec:
    plausible = raw.get("plausible_range")
    return FieldSpec(
        name=name,
        kind=AccessorKind(raw["kind"]),
        type=raw["type"],
        in_scope=bool(raw.get("in_scope", True)),
        renderable=bool(raw.get("renderable", True)),
        informational=bool(raw.get("informational", False)),
        display=raw.get("display", name),
        aliases=tuple(raw.get("aliases", ())),
        plausible_range=tuple(plausible) if plausible else None,
        out_of_scope_reason=raw.get("out_of_scope_reason"),
    )


def _parse_source(
    raw: dict[str, Any],
) -> tuple[
    ProductSpec,
    dict[str, FieldSpec],
    tuple[Rule, ...],
    ProcessPolicy,
    tuple[UnreachableCode, ...],
    tuple[OutOfSchemaConcept, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    product_raw = raw["product"]
    product = ProductSpec(
        name=product_raw["name"],
        kind=product_raw["kind"],
        secured=bool(product_raw["secured"]),
        min_amount_cents=int(product_raw["min_amount_cents"]),
        max_amount_cents=int(product_raw["max_amount_cents"]),
        min_term_months=int(product_raw["min_term_months"]),
        max_term_months=int(product_raw["max_term_months"]),
    )

    fields = {name: _parse_field(name, spec) for name, spec in raw["fields"].items()}
    rules = tuple(_parse_rule(r) for r in raw["rules"])

    process_raw = raw["process"]
    process = ProcessPolicy(
        decision_tool=process_raw["decision_tool"],
        required_tools_before_decision=tuple(process_raw["required_tools_before_decision"]),
        required_tools_before_code={
            k: tuple(v) for k, v in process_raw.get("required_tools_before_code", {}).items()
        },
        prohibited_tools=tuple(process_raw["prohibited_tools"]),
        prohibited_factors=tuple(
            ProhibitedFactor(
                factor=f["factor"], basis=f["basis"], aliases=tuple(f.get("aliases", ()))
            )
            for f in process_raw["prohibited_factors"]
        ),
        max_stated_reasons=int(process_raw["max_stated_reasons"]),
        min_stated_reasons_on_adverse_action=int(
            process_raw["min_stated_reasons_on_adverse_action"]
        ),
        max_steps=int(process_raw["max_steps"]),
    )

    unreachable = tuple(
        UnreachableCode(
            code=ReasonCode(u["code"]), verdict=u["verdict"], note=" ".join(u["note"].split())
        )
        for u in raw.get("unreachable_codes", ())
    )
    concepts = tuple(
        OutOfSchemaConcept(concept=c["concept"], aliases=tuple(c.get("aliases", ())))
        for c in raw.get("out_of_schema_concepts", ())
    )
    generated_blocks = tuple(raw["generated_blocks"])
    allowlist = tuple(str(a["literal"]) for a in raw.get("prose_numeric_allowlist", ()))

    return product, fields, rules, process, unreachable, concepts, generated_blocks, allowlist


# --------------------------------------------------------------------------------------
# A0: YAML self-consistency
# --------------------------------------------------------------------------------------


def _check_a0_self_consistency(
    fields: dict[str, FieldSpec],
    rules: tuple[Rule, ...],
    unreachable: tuple[UnreachableCode, ...],
) -> None:
    seen_ids: set[str] = set()
    for rule in rules:
        if rule.rule_id in seen_ids:
            raise PolicySchemaError(f"duplicate rule_id: {rule.rule_id}")
        seen_ids.add(rule.rule_id)

    unreachable_codes = {u.code for u in unreachable}
    for rule in rules:
        if rule.reason_code in unreachable_codes:
            raise PolicySchemaError(
                f"{rule.rule_id} uses {rule.reason_code}, which is declared unreachable"
            )

        acc = rule.accessor
        if acc.kind is AccessorKind.PRIMITIVE:
            if acc.field not in _FinancialFacts.model_fields:
                raise PolicySchemaError(f"{rule.rule_id}: unknown primitive field {acc.field!r}")
        elif acc.kind is AccessorKind.PROPERTY:
            if not isinstance(getattr(_FinancialFacts, acc.field, None), property):
                raise PolicySchemaError(f"{rule.rule_id}: {acc.field!r} is not a property")
            # A rule reading a property accessor is what makes that property "scored" --
            # renderable_fields (and anything else reading the registry) needs a `fields:`
            # entry for it or it silently disappears from what the agent is shown even
            # though a rule still enforces it. Checking against the class alone (above)
            # verifies the accessor is real; it does not verify the registry knows about
            # it -- those are two different pieces of data, and this closes the gap
            # between them.
            spec = fields.get(acc.field)
            if spec is None:
                raise PolicyRegistryError(
                    f"{rule.rule_id}: property {acc.field!r} is read by a rule but has no "
                    "fields: registry entry"
                )
            if spec.kind is not AccessorKind.PROPERTY:
                raise PolicyRegistryError(
                    f"{rule.rule_id}: property {acc.field!r}'s fields: entry has "
                    f"kind={spec.kind.value!r}, expected 'property'"
                )
        elif acc.kind is AccessorKind.DERIVED:
            from credit_audit.policy.oracle import ACCESSORS  # local: avoid import cycle

            if acc.name not in ACCESSORS:
                raise PolicySchemaError(
                    f"{rule.rule_id}: unregistered derived accessor {acc.name!r}"
                )

        for field_name in rule.repair.fields:
            if field_name not in _FinancialFacts.model_fields:
                raise PolicySchemaError(
                    f"{rule.rule_id}: repair field {field_name!r} is not a FinancialFacts "
                    "primitive -- repairs must set primitives, never computed properties"
                )

    # No code may have two rules whose repairs move the same field in opposite directions.
    by_code: dict[ReasonCode, list[Rule]] = {}
    for rule in rules:
        by_code.setdefault(rule.reason_code, []).append(rule)
    for code, code_rules in by_code.items():
        directions: dict[str, str] = {}
        for rule in code_rules:
            for field_name in rule.repair.fields:
                prior = directions.get(field_name)
                if prior is not None and prior != rule.repair.direction:
                    raise PolicySchemaError(
                        f"{code}: rules move {field_name!r} in opposite directions "
                        f"({prior} vs {rule.repair.direction})"
                    )
                directions[field_name] = rule.repair.direction

    # Every PublicRecordKind must be covered by at least one rule's `kinds` param, or a
    # new record kind could be added to types.py and never policed by any rule.
    covered_kinds: set[str] = set()
    for rule in rules:
        if rule.accessor.kind is AccessorKind.DERIVED:
            covered_kinds.update(rule.accessor.params.get("kinds", ()))
        covered_kinds.update(rule.repair.params.get("remove_kinds", ()))
    missing_kinds = {k.value for k in PublicRecordKind} - covered_kinds
    if missing_kinds:
        raise PolicySchemaError(f"PublicRecordKind values with no policing rule: {missing_kinds}")


# --------------------------------------------------------------------------------------
# A4: registry completeness
# --------------------------------------------------------------------------------------


def _check_a4_registry_completeness(fields: dict[str, FieldSpec], process: ProcessPolicy) -> None:
    primitive_fields = {
        name for name, spec in fields.items() if spec.kind is AccessorKind.PRIMITIVE
    }
    expected = set(_FinancialFacts.model_fields)
    if primitive_fields != expected:
        missing = expected - primitive_fields
        extra = primitive_fields - expected
        raise PolicyRegistryError(
            f"fields registry does not match FinancialFacts. missing={missing} extra={extra}"
        )

    declared_factors = {f.factor for f in process.prohibited_factors}
    expected_presentation = set(Presentation.model_fields)
    if not expected_presentation.issubset(declared_factors):
        missing = expected_presentation - declared_factors
        raise PolicyRegistryError(
            f"prohibited_factors does not cover every Presentation field. missing={missing}"
        )


# --------------------------------------------------------------------------------------
# format_value -- the one function generation and export both go through
# --------------------------------------------------------------------------------------


def format_value(field_type: str, value: Any) -> str:
    """Render a value for display, exactly as it should appear in generated prose.

    The generated blocks and the export projection (Phase 8) must format numbers
    identically, or the document and the site would silently diverge in a way no test in
    this module could catch. Both are required to route through this function.
    """
    if field_type == "int_cents":
        cents = int(value)
        dollars, remainder = divmod(abs(cents), 100)
        sign = "-" if cents < 0 else ""
        return f"{sign}${dollars:,}" if remainder == 0 else f"{sign}${dollars:,}.{remainder:02d}"
    if field_type == "ratio":
        pct = Decimal(value) * 100
        return f"{pct.normalize():f}%" if pct == pct.to_integral() else f"{pct}%"
    if field_type == "bool":
        return "yes" if value else "no"
    return str(value)


def _value_renderings(value: Decimal | int | str) -> set[str]:
    """Every textual form a declared value is allowed to take in hand-written prose."""
    out = {str(value)}
    if isinstance(value, Decimal):
        out.add(str(value.normalize()))
        as_pct = value * 100
        out.add(f"{as_pct.normalize():f}")
        out.add(f"{as_pct.normalize():f}%")
    if isinstance(value, int):
        out.add(f"{value:,}")
    return out


# --------------------------------------------------------------------------------------
# Generated block rendering
# --------------------------------------------------------------------------------------


def _rule_field_display(rule: Rule) -> str:
    if rule.accessor.kind is AccessorKind.DERIVED:
        return rule.accessor.name  # type: ignore[return-value]
    return rule.accessor.field  # type: ignore[return-value]


def render_generated_block(
    block_id: str,
    *,
    product: ProductSpec,
    fields: dict[str, FieldSpec],
    rules: tuple[Rule, ...],
    process: ProcessPolicy,
    unreachable: tuple[UnreachableCode, ...],
) -> str:
    """Deterministic markdown body for one generated block.

    LF-only, no trailing whitespace on any line, exactly one trailing newline. Called
    both to render policy.md and, independently, to check what is already there --
    the two call sites must never diverge in behaviour, so there is only one function.
    """
    lines: list[str]

    if block_id == "product":
        lines = [
            f"- **Product:** {product.name} ({product.kind.replace('_', ' ')})",
            f"- **Secured:** {'yes' if product.secured else 'no'}",
            "- **Loan amount:** "
            f"{format_value('int_cents', product.min_amount_cents)} - "
            f"{format_value('int_cents', product.max_amount_cents)}",
            f"- **Term:** {product.min_term_months} - {product.max_term_months} months",
        ]

    elif block_id == "credit_standards":
        lines = []
        by_section: dict[str, list[Rule]] = {}
        for rule in rules:
            by_section.setdefault(rule.section, []).append(rule)
        titles = {
            "4.1": "Capacity",
            "4.2": "Credit history",
            "4.3": "Derogatory credit",
            "4.4": "Employment and income documentation",
        }
        for section in sorted(by_section):
            lines.append(f"### {section} {titles.get(section, section)}")
            lines.append("")
            lines.append("| Rule | Standard | Value | Adverse-action reason code |")
            lines.append("|---|---|---|---|")
            for rule in by_section[section]:
                # display_value is threshold-derived for every numeric rule, so this
                # column changes whenever threshold changes -- that is what makes a
                # threshold edit without a re-sync a detectable A1 divergence, rather
                # than an edit the generated block happens not to reflect anywhere.
                row = (
                    f"| {rule.rule_id} | {rule.statement} | {rule.display_value} "
                    f"| {rule.reason_code} |"
                )
                lines.append(row)
            lines.append("")
        if lines and lines[-1] == "":
            lines.pop()

    elif block_id == "decision_procedure":
        lines = [
            f"- **Decision tool:** `{process.decision_tool}`",
            "- **Required before any decision:** "
            + ", ".join(f"`{t}`" for t in process.required_tools_before_decision),
        ]
        for code, tools in process.required_tools_before_code.items():
            lines.append(
                f"- **Required before citing `{code}`:** " + ", ".join(f"`{t}`" for t in tools)
            )
        lines.append(
            "- **Prohibited tools (never call):** "
            + ", ".join(f"`{t}`" for t in process.prohibited_tools)
        )
        lines.append(f"- **Maximum stated reasons:** {process.max_stated_reasons}")
        lines.append(
            "- **Minimum stated reasons on adverse action:** "
            f"{process.min_stated_reasons_on_adverse_action}"
        )
        lines.append(f"- **Maximum reasoning steps:** {process.max_steps}")

    elif block_id == "prohibited_factors":
        lines = ["The following must never influence a credit decision under this policy:", ""]
        for factor in process.prohibited_factors:
            basis = (
                "Regulation B protected basis"
                if factor.basis == "reg_b"
                else "non-substantive presentation feature"
            )
            lines.append(f"- **{factor.factor}** ({basis})")

    elif block_id == "out_of_scope_factors":
        lines = [
            "This product is unsecured. The following are outside the scope of this "
            "policy and must not be cited as a basis for any decision:",
            "",
        ]
        for spec in fields.values():
            if not spec.in_scope and spec.out_of_scope_reason:
                lines.append(f"- **{spec.display}**: {spec.out_of_scope_reason.strip()}")

    elif block_id == "reason_codes":
        lines = []
        seen: dict[ReasonCode, list[str]] = {}
        for rule in rules:
            seen.setdefault(rule.reason_code, []).append(rule.rule_id)
        for code, rule_ids in seen.items():
            first = next(r for r in rules if r.rule_id == rule_ids[0])
            lines.append(f"- `{code}` (§{first.section}): {first.statement}")
        for u in unreachable:
            lines.append(f"- `{u.code}`: never a legitimate reason under this policy. {u.note}")

    else:
        raise PolicySchemaError(f"unknown generated block id: {block_id!r}")

    body = "\n".join(line.rstrip() for line in lines)
    return body + "\n"


def find_generated_blocks(md_text: str) -> dict[str, tuple[int, int, str]]:
    """Locate every BEGIN/END marker pair. Returns block_id -> (body_start, body_end, body).

    Raises on duplicate, unclosed, out-of-order, or overlapping markers -- these are
    parser-robustness failures distinct from a content mismatch (A1 checks content
    separately, in ``check_generated_blocks``).
    """
    begins = list(_BEGIN_RE.finditer(md_text))
    ends = list(_END_RE.finditer(md_text))

    begin_ids = [m.group("id") for m in begins]
    if len(begin_ids) != len(set(begin_ids)):
        raise PolicyDivergenceError(f"duplicate BEGIN markers: {begin_ids}")
    end_ids = [m.group("id") for m in ends]
    if len(end_ids) != len(set(end_ids)):
        raise PolicyDivergenceError(f"duplicate END markers: {end_ids}")
    if set(begin_ids) != set(end_ids):
        raise PolicyDivergenceError(
            f"BEGIN/END marker mismatch: begins={set(begin_ids)} ends={set(end_ids)}"
        )

    blocks: dict[str, tuple[int, int, str]] = {}
    for begin in begins:
        block_id = begin.group("id")
        matching_ends = [e for e in ends if e.group("id") == block_id]
        end = matching_ends[0]
        if end.start() < begin.end():
            raise PolicyDivergenceError(f"{block_id}: END appears before BEGIN")
        body = md_text[begin.end() : end.start()]
        blocks[block_id] = (
            begin.end(),
            end.start(),
            body.strip("\n") + "\n" if body.strip() else "",
        )
    return blocks


def check_generated_blocks(
    md_text: str,
    *,
    product: ProductSpec,
    fields: dict[str, FieldSpec],
    rules: tuple[Rule, ...],
    process: ProcessPolicy,
    unreachable: tuple[UnreachableCode, ...],
    declared_block_ids: tuple[str, ...],
) -> list[str]:
    """Return a list of human-readable divergence descriptions. Empty means consistent.

    Checks presence first: the declared block set must equal the found block set. This
    is the assertion a naive regenerate-and-diff loop typically omits -- if a block's
    markers are deleted, that loop iterates over zero blocks and silently passes.
    """
    found = find_generated_blocks(md_text)
    problems: list[str] = []

    declared = set(declared_block_ids)
    found_ids = set(found)
    if declared != found_ids:
        missing = declared - found_ids
        extra = found_ids - declared
        problems.append(f"generated block set mismatch: missing={missing} extra={extra}")

    for block_id in declared & found_ids:
        _, _, actual_body = found[block_id]
        expected_body = render_generated_block(
            block_id,
            product=product,
            fields=fields,
            rules=rules,
            process=process,
            unreachable=unreachable,
        )
        if actual_body != expected_body:
            diff = "\n".join(
                difflib.unified_diff(
                    actual_body.splitlines(),
                    expected_body.splitlines(),
                    fromfile=f"policy.md#{block_id}",
                    tofile="rendered from policy.yaml",
                    lineterm="",
                )
            )
            problems.append(f"block {block_id!r} diverges:\n{diff}")

    return problems


def sync(md_path: Path = MD_PATH, yaml_path: Path = YAML_PATH) -> bool:
    """Regenerate every declared block in policy.md in place. Returns True if anything changed.

    This is the fix command PolicyDivergenceError points readers to:
    `python -m credit_audit.policy.loader --sync`.
    """
    with open(yaml_path, encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    reject_floats(raw)
    product, fields, rules, process, unreachable, _concepts, block_ids, _allow = _parse_source(raw)

    md_text = md_path.read_text(encoding="utf-8")
    found = find_generated_blocks(md_text)
    changed = False
    for block_id in block_ids:
        if block_id not in found:
            raise PolicyDivergenceError(f"cannot sync: block {block_id!r} markers not found")
        start, end, current_body = found[block_id]
        new_body = render_generated_block(
            block_id,
            product=product,
            fields=fields,
            rules=rules,
            process=process,
            unreachable=unreachable,
        )
        if current_body != new_body:
            md_text = md_text[:start] + "\n" + new_body + md_text[end:]
            changed = True
            found = find_generated_blocks(md_text)
    if changed:
        md_path.write_text(md_text, encoding="utf-8")
    return changed


# --------------------------------------------------------------------------------------
# A2: cross-reference resolution + section parsing
# --------------------------------------------------------------------------------------


def parse_sections(md_text: str) -> tuple[PolicySection, ...]:
    lines = md_text.split("\n")
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line) + 1)

    headings: list[tuple[int, str, str, int]] = []
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m:
            headings.append((i, m.group("anchor"), m.group("title"), len(m.group("level"))))

    sections: list[PolicySection] = []
    for idx, (line_no, anchor, title, level) in enumerate(headings):
        start = offsets[line_no]
        end = offsets[headings[idx + 1][0]] if idx + 1 < len(headings) else len(md_text)
        sections.append(
            PolicySection(anchor=anchor, title=title, level=level, start=start, end=end)
        )
    return tuple(sections)


def _check_a2_references(
    md_text: str, sections: tuple[PolicySection, ...], rules: tuple[Rule, ...]
) -> None:
    known_anchors = {s.anchor for s in sections}
    for rule in rules:
        if rule.anchor not in known_anchors:
            raise PolicyReferenceError(
                f"{rule.rule_id}: anchor {rule.anchor!r} has no matching heading"
            )

    for m in _XREF_RE.finditer(md_text):
        anchor = m.group(1)
        if anchor not in known_anchors:
            raise PolicyReferenceError(f"dangling cross-reference §{anchor} in policy.md")


# --------------------------------------------------------------------------------------
# A3: numeric lint on hand-written prose
# --------------------------------------------------------------------------------------


def _declared_numeric_renderings(
    product: ProductSpec,
    rules: tuple[Rule, ...],
    process: ProcessPolicy,
) -> set[str]:
    declared: set[str] = set()
    for rule in rules:
        if rule.threshold is not None:
            declared |= _value_renderings(rule.threshold)
        declared |= _value_renderings(rule.margin_unit)
        declared.add(rule.display_value.rstrip("%").replace(",", "").replace("$", ""))
        declared.add(rule.display_value)
    for value in (
        product.min_amount_cents,
        product.max_amount_cents,
        product.min_term_months,
        product.max_term_months,
        process.max_stated_reasons,
        process.min_stated_reasons_on_adverse_action,
        process.max_steps,
    ):
        declared |= _value_renderings(value)
    return declared


def check_prose_numerics(
    md_text: str,
    *,
    product: ProductSpec,
    rules: tuple[Rule, ...],
    process: ProcessPolicy,
    allowlist: tuple[str, ...],
) -> list[str]:
    """Scan only hand-written regions (outside generated blocks) for numeric literals
    that cannot be traced to a declared value. Returns human-readable problem strings."""
    blocks = find_generated_blocks(md_text)
    excluded_spans: list[tuple[int, int]] = []
    for m in _BEGIN_RE.finditer(md_text):
        block_id = m.group("id")
        if block_id in blocks:
            body_start, body_end, _ = blocks[block_id]
            excluded_spans.append((m.start(), body_end))

    def in_generated(pos: int) -> bool:
        return any(start <= pos < end for start, end in excluded_spans)

    declared = _declared_numeric_renderings(product, rules, process)
    allowed = declared | set(allowlist) | {"1", "2", "3", "4"}  # small ordinals in headings
    problems: list[str] = []
    for m in _NUMBER_RE.finditer(md_text):
        if in_generated(m.start()):
            continue
        literal = m.group().rstrip("%")
        normalized = literal.replace(",", "")
        if literal in allowed or normalized in allowed:
            continue
        # Heading numerals ("## 4. Credit standards") are structural, not policy content.
        line_start = md_text.rfind("\n", 0, m.start()) + 1
        if md_text[line_start : m.start()].lstrip().startswith("#"):
            continue
        # Internal cross-references ("Section 5", "§4.4") are structural: A2 already
        # verifies they resolve to a real heading. Content numbers never follow "Section"
        # or "§", so this cannot be used to smuggle a real threshold past the lint.
        preceding = md_text[max(0, m.start() - 12) : m.start()]
        if preceding.rstrip().endswith("§") or re.search(r"[Ss]ection\s*$", preceding):
            continue
        problems.append(f"unrecognized numeral {m.group()!r} at offset {m.start()}")
    return problems


# --------------------------------------------------------------------------------------
# load_policy
# --------------------------------------------------------------------------------------


@lru_cache(maxsize=4)
def load_policy(
    md_path: Path = MD_PATH, yaml_path: Path = YAML_PATH, *, strict: bool = True
) -> Policy:
    """Load, validate, and return the policy. Cached: evaluate() runs this hot.

    With strict=True (the default, and the only mode used in production), all five
    consistency assertions run. A tampered policy.md or policy.yaml fails the run rather
    than silently producing wrong ground truth.
    """
    with open(yaml_path, encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    reject_floats(raw)

    if raw.get("schema") != "credit-audit/policy-source@1":
        raise PolicySchemaError(f"unexpected schema: {raw.get('schema')!r}")

    product, fields, rules, process, unreachable, concepts, block_ids, allowlist = _parse_source(
        raw
    )

    if strict:
        _check_a0_self_consistency(fields, rules, unreachable)
        _check_a4_registry_completeness(fields, process)

    md_text = md_path.read_text(encoding="utf-8")
    sections = parse_sections(md_text)

    if strict:
        _check_a2_references(md_text, sections, rules)

        divergences = check_generated_blocks(
            md_text,
            product=product,
            fields=fields,
            rules=rules,
            process=process,
            unreachable=unreachable,
            declared_block_ids=block_ids,
        )
        if divergences:
            raise PolicyDivergenceError(
                "policy.md and policy.yaml have diverged:\n\n"
                + "\n\n".join(divergences)
                + "\n\nFix: python -m credit_audit.policy.loader --sync"
            )

        prose_problems = check_prose_numerics(
            md_text,
            product=product,
            rules=rules,
            process=process,
            allowlist=allowlist,
        )
        if prose_problems:
            raise PolicyProseNumberError(
                "policy.md contains numerals not traceable to policy.yaml:\n"
                + "\n".join(prose_problems)
                + "\n\nEither the number is wrong, or it belongs in "
                "prose_numeric_allowlist with a stated reason."
            )

    return Policy(
        version=raw["version"],
        product=product,
        fields=fields,
        rules=rules,
        unreachable_codes=unreachable,
        out_of_schema_concepts=concepts,
        process=process,
        prose_numeric_allowlist=allowlist,
        doc=PolicyDoc(text=md_text, sections=sections),
        md_sha256=sha256_file(md_path),
        yaml_sha256=sha256_file(yaml_path),
    )


def export_policy_snapshot(policy: Policy) -> dict[str, Any]:
    """Project a loaded Policy onto schemas/export/policy.schema.json.

    Written now, in Phase 1, and tested against the schema Phase 0 already froze --
    which keeps this phase honest against the Phase 8 exporter with zero Phase 8 code.
    """
    thresholds = []
    for rule in policy.rules:
        if rule.predicate in (PredicateKind.NUMERIC_MIN, PredicateKind.NUMERIC_MAX):
            operator = ">=" if rule.predicate is PredicateKind.NUMERIC_MIN else "<="
            value: Any = str(rule.threshold)
        else:
            # flag_true / enum_allowed are evaluated as an indicator >= 1 (see oracle.py);
            # the export mirrors that so it needs no new schema shape.
            operator = ">="
            value = "1"
        thresholds.append(
            {
                "id": rule.rule_id,
                "field": _rule_field_display(rule),
                "operator": operator,
                "value": value,
                "reason_code": rule.reason_code.value,
                "anchor": rule.anchor,
                "description": rule.statement,
            }
        )

    return {
        "schema": "credit-audit/policy@1",
        "version": policy.version,
        "md_sha256": policy.md_sha256,
        "yaml_sha256": policy.yaml_sha256,
        "product": {
            "name": policy.product.name,
            "secured": policy.product.secured,
            "synthetic": True,
        },
        "thresholds": thresholds,
        "required_tools_before_decision": list(policy.process.required_tools_before_decision),
        "required_tools_before_code": {
            code: list(tools) for code, tools in policy.process.required_tools_before_code.items()
        },
        "prohibited_tools": list(policy.process.prohibited_tools),
        "prohibited_factors": [f.factor for f in policy.process.prohibited_factors],
        "min_stated_reasons": policy.process.min_stated_reasons_on_adverse_action,
        "max_stated_reasons": policy.process.max_stated_reasons,
    }


if __name__ == "__main__":
    import sys

    if "--sync" in sys.argv:
        changed = sync()
        print("policy.md updated" if changed else "policy.md already in sync")
    else:
        load_policy()
        print("policy loads and validates cleanly")
