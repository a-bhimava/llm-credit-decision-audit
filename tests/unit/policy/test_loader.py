"""The policy.md / policy.yaml consistency gate.

The mutation tests are the load-bearing ones in this file: they corrupt one committed
file at a time and assert the loader raises. A consistency check that has never been
observed to fail is not a gate -- the single most likely real-world outcome of this kind
of design is that the check silently never fires (wrong markers, comparing a file against
itself, an exception swallowed somewhere) and drift arrives with nobody noticing.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
import yaml

from credit_audit.policy import loader
from credit_audit.policy.loader import (
    MD_PATH,
    YAML_PATH,
    Policy,
    PolicyDivergenceError,
    PolicyFloatError,
    PolicyProseNumberError,
    PolicyReferenceError,
    PolicySchemaError,
    load_policy,
)
from credit_audit.policy.oracle import evaluate
from credit_audit.types import EmploymentStatus, FinancialFacts


@pytest.fixture
def tmp_policy_files(tmp_path: Path) -> tuple[Path, Path]:
    md = tmp_path / "policy.md"
    yml = tmp_path / "policy.yaml"
    shutil.copy(MD_PATH, md)
    shutil.copy(YAML_PATH, yml)
    return md, yml


def _load(md: Path, yml: Path, **kwargs) -> Policy:
    load_policy.cache_clear()
    return load_policy(md, yml, **kwargs)


# --------------------------------------------------------------------------------------
# The gate passes on the real, committed files
# --------------------------------------------------------------------------------------


def test_committed_policy_loads_and_validates():
    load_policy.cache_clear()
    policy = load_policy()
    assert len(policy.rules) == 16
    assert policy.md_sha256.startswith("sha256:")
    assert policy.yaml_sha256.startswith("sha256:")


def test_load_policy_is_cached():
    load_policy.cache_clear()
    a = load_policy()
    b = load_policy()
    assert a is b


# --------------------------------------------------------------------------------------
# The gate can fail: mutate one committed file at a time
# --------------------------------------------------------------------------------------


def test_mutated_yaml_threshold_raises_divergence(tmp_policy_files):
    md, yml = tmp_policy_files
    text = yml.read_text()
    mutated = text.replace('threshold: "0.43"', 'threshold: "0.45"')
    assert mutated != text, "fixture setup bug: the target string was not found"
    yml.write_text(mutated)
    with pytest.raises(PolicyDivergenceError):
        _load(md, yml)


def test_mutated_md_block_raises_divergence(tmp_policy_files):
    md, yml = tmp_policy_files
    text = md.read_text()
    mutated = text.replace("must be at least 640", "must be at least 999", 1)
    assert mutated != text
    md.write_text(mutated)
    with pytest.raises(PolicyDivergenceError):
        _load(md, yml)


def test_deleted_block_markers_raise(tmp_policy_files):
    md, yml = tmp_policy_files
    text = md.read_text()
    mutated = re.sub(r"<!-- (BEGIN|END) GENERATED policy\.yaml:product -->\n?", "", text)
    assert mutated != text
    md.write_text(mutated)
    with pytest.raises(PolicyDivergenceError):
        _load(md, yml)


def test_duplicate_begin_markers_raise(tmp_policy_files):
    md, yml = tmp_policy_files
    text = md.read_text()
    marker = "<!-- BEGIN GENERATED policy.yaml:product -->"
    mutated = text.replace(marker, marker + "\n" + marker, 1)
    md.write_text(mutated)
    with pytest.raises(PolicyDivergenceError):
        _load(md, yml)


def test_stray_prose_number_raises(tmp_policy_files):
    md, yml = tmp_policy_files
    text = md.read_text()
    insert = "A score of at least 660 is generally preferred. "
    mutated = text.replace(
        "This policy does not provide for manual override",
        insert + "This policy does not provide for manual override",
        1,
    )
    assert mutated != text
    md.write_text(mutated)
    with pytest.raises(PolicyProseNumberError):
        _load(md, yml)


def test_allowlisted_citation_number_passes(tmp_policy_files):
    """The lint isn't so strict it rejects the document's own legitimate citations."""
    md, yml = tmp_policy_files
    _load(md, yml)  # the committed doc already cites 1002.9, 1691, 15 -- must not raise


def test_yaml_float_raises(tmp_path):
    md = tmp_path / "policy.md"
    yml = tmp_path / "policy.yaml"
    shutil.copy(MD_PATH, md)
    raw = yaml.safe_load(YAML_PATH.read_text())
    raw["rules"][0]["threshold"] = 0.43  # unquoted -> float
    yml.write_text(yaml.safe_dump(raw, sort_keys=False))
    with pytest.raises(PolicyFloatError):
        _load(md, yml)


# --------------------------------------------------------------------------------------
# A0 self-consistency
# --------------------------------------------------------------------------------------


def test_every_public_record_kind_is_policed():
    from credit_audit.types import PublicRecordKind

    policy = load_policy()
    covered: set[str] = set()
    for rule in policy.rules:
        if rule.accessor.kind.value == "derived":
            covered.update(rule.accessor.params.get("kinds", ()))
        covered.update(rule.repair.params.get("remove_kinds", ()))
    assert covered == {k.value for k in PublicRecordKind}


def test_no_rule_uses_an_unreachable_code():
    policy = load_policy()
    unreachable = {u.code for u in policy.unreachable_codes}
    used = {r.reason_code for r in policy.rules}
    assert not (unreachable & used)


def test_repair_fields_are_primitives_not_properties():
    policy = load_policy()
    for rule in policy.rules:
        for field_name in rule.repair.fields:
            assert field_name in FinancialFacts.model_fields, (
                f"{rule.rule_id} repair field {field_name!r} must be a stored primitive"
            )


def test_duplicate_rule_id_raises(tmp_policy_files):
    md, yml = tmp_policy_files
    raw = yaml.safe_load(yml.read_text())
    raw["rules"].append(dict(raw["rules"][0]))  # exact duplicate, including rule_id
    yml.write_text(yaml.safe_dump(raw, sort_keys=False))
    with pytest.raises(PolicySchemaError):
        _load(md, yml)


def test_rule_using_unreachable_code_raises(tmp_policy_files):
    md, yml = tmp_policy_files
    raw = yaml.safe_load(yml.read_text())
    raw["rules"][0]["reason_code"] = "COLLATERAL_VALUE_INSUFFICIENT"
    yml.write_text(yaml.safe_dump(raw, sort_keys=False))
    with pytest.raises(PolicySchemaError):
        _load(md, yml)


def test_opposite_direction_repairs_on_same_field_raises(tmp_policy_files):
    md, yml = tmp_policy_files
    raw = yaml.safe_load(yml.read_text())
    # Two rules already share INSUFFICIENT_INCOME via annual_income_cents, both
    # "increase". Flip one to "decrease" and the self-consistency check must catch it.
    for rule in raw["rules"]:
        if rule["rule_id"] == "max_loan_to_income":
            rule["repair"]["direction"] = "decrease"
    yml.write_text(yaml.safe_dump(raw, sort_keys=False))
    with pytest.raises(PolicySchemaError):
        _load(md, yml)


# --------------------------------------------------------------------------------------
# A2 references
# --------------------------------------------------------------------------------------


def test_every_rule_anchor_resolves():
    policy = load_policy()
    anchors = {s.anchor for s in policy.doc.sections}
    for rule in policy.rules:
        assert rule.anchor in anchors


def test_dangling_rule_anchor_raises(tmp_policy_files):
    md, yml = tmp_policy_files
    raw = yaml.safe_load(yml.read_text())
    raw["rules"][0]["anchor"] = "99.9"
    yml.write_text(yaml.safe_dump(raw, sort_keys=False))
    with pytest.raises(PolicyReferenceError):
        _load(md, yml)


# --------------------------------------------------------------------------------------
# A4 registry completeness
# --------------------------------------------------------------------------------------


def test_field_registry_covers_financial_facts():
    policy = load_policy()
    primitive_fields = {
        name for name, spec in policy.fields.items() if spec.kind.value == "primitive"
    }
    assert primitive_fields == set(FinancialFacts.model_fields)


def test_prohibited_factors_cover_presentation():
    from credit_audit.types import Presentation

    policy = load_policy()
    declared = {f.factor for f in policy.process.prohibited_factors}
    assert set(Presentation.model_fields).issubset(declared)


def test_missing_field_from_registry_raises(tmp_policy_files):
    md, yml = tmp_policy_files
    raw = yaml.safe_load(yml.read_text())
    del raw["fields"]["credit_score"]
    yml.write_text(yaml.safe_dump(raw, sort_keys=False))
    with pytest.raises(loader.PolicyError):
        # A4 (registry completeness) is what actually fires here -- the fields registry
        # no longer covers FinancialFacts.credit_score. A0's accessor check would only
        # fire if credit_score's *rule* referenced a name outside FinancialFacts itself,
        # which is a different failure. Either way, load must not silently succeed.
        _load(md, yml)


# --------------------------------------------------------------------------------------
# render_generated_block byte-stability
# --------------------------------------------------------------------------------------


def test_render_block_is_byte_stable_across_calls():
    policy = load_policy()

    kwargs = dict(
        product=policy.product,
        fields=policy.fields,
        rules=policy.rules,
        process=policy.process,
        unreachable=policy.unreachable_codes,
    )
    for block_id in (
        "product",
        "credit_standards",
        "decision_procedure",
        "prohibited_factors",
        "out_of_scope_factors",
        "reason_codes",
    ):
        a = loader.render_generated_block(block_id, **kwargs)
        b = loader.render_generated_block(block_id, **kwargs)
        assert a == b
        assert not any(line != line.rstrip() for line in a.split("\n")[:-1]), "trailing whitespace"
        assert a.endswith("\n")


def test_sync_is_idempotent(tmp_policy_files):
    md, yml = tmp_policy_files
    changed_once = loader.sync(md, yml)
    assert changed_once is False, "the committed policy.md is already in sync"
    changed_twice = loader.sync(md, yml)
    assert changed_twice is False, "a second sync must be a no-op"


# --------------------------------------------------------------------------------------
# export_policy_snapshot vs. the frozen Phase 0 schema
# --------------------------------------------------------------------------------------


def test_export_snapshot_validates_against_frozen_policy_schema():
    import json

    from jsonschema import Draft202012Validator

    policy = load_policy()
    snapshot = loader.export_policy_snapshot(policy)

    schema_path = Path(__file__).resolve().parents[3] / "schemas" / "export" / "policy.schema.json"
    schema = json.loads(schema_path.read_text())
    Draft202012Validator(schema).validate(snapshot)

    assert len(snapshot["thresholds"]) == 16
    assert snapshot["product"]["secured"] is False
    assert snapshot["product"]["synthetic"] is True


# --------------------------------------------------------------------------------------
# Registered accessors are actually usable end to end
# --------------------------------------------------------------------------------------


def test_loaded_policy_evaluates_a_facts_instance():
    policy = load_policy()
    facts = FinancialFacts(
        annual_income_cents=6_000_000,
        monthly_debt_cents=60_000,
        loan_amount_cents=800_000,
        property_value_cents=0,
        loan_term_months=48,
        credit_score=740,
        open_tradelines=6,
        revolving_balance_cents=200_000,
        revolving_limit_cents=1_000_000,
        delinq_30d_24m=0,
        delinq_60d_24m=0,
        delinq_90p_24m=0,
        oldest_tradeline_months=96,
        inquiries_6m=1,
        employment_months=60,
        employment_status=EmploymentStatus.FULL_TIME,
        income_documented=True,
    )
    decision = evaluate(facts, policy)
    assert decision.outcome.value == "APPROVE"
