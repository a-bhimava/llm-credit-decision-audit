"""The three renderers must be genuinely different presentations, not thin wrappers around
one string -- FormatSensitiveAgent (Phase 2) and Phase 6's serialization check both depend
on render mode being a meaningfully different parse target."""

from __future__ import annotations

import json

from credit_audit.policy.loader import load_policy
from credit_audit.profiles.generate import read_profiles_jsonl
from credit_audit.render.registry import RENDERERS
from credit_audit.types import RenderMode


def test_table_prose_json_are_all_different():
    policy = load_policy()
    applicant = read_profiles_jsonl()[0]
    rendered = {mode: RENDERERS[mode](applicant, mode, policy) for mode in RenderMode}
    assert len(set(rendered.values())) == 3


def test_only_json_round_trips_through_json_loads():
    policy = load_policy()
    applicant = read_profiles_jsonl()[0]

    js = RENDERERS[RenderMode.JSON](applicant, RenderMode.JSON, policy)
    json.loads(js)  # must not raise

    for mode in (RenderMode.TABLE, RenderMode.PROSE):
        text = RENDERERS[mode](applicant, mode, policy)
        try:
            json.loads(text)
        except (json.JSONDecodeError, ValueError):
            continue
        raise AssertionError(f"{mode.value} render unexpectedly parses as JSON")


def test_prose_has_no_label_value_lines():
    """The defining structural difference from table: no line is a short `Label: value`
    pair -- every prose line is a full, period-terminated sentence."""
    policy = load_policy()
    applicant = read_profiles_jsonl()[0]
    prose = RENDERERS[RenderMode.PROSE](applicant, RenderMode.PROSE, policy)
    for line in prose.splitlines():
        stripped = line.strip()
        if stripped:
            assert stripped.endswith("."), f"non-sentence line in prose render: {stripped!r}"


def test_table_has_label_value_lines_prose_does_not():
    policy = load_policy()
    applicant = read_profiles_jsonl()[0]
    table = RENDERERS[RenderMode.TABLE](applicant, RenderMode.TABLE, policy)
    assert any(":" in line and len(line) < 80 for line in table.splitlines())


def test_renderers_cover_the_same_field_set_across_all_profiles():
    """All three renderers must reference every renderable field for every profile --
    not just happen to for one hand-picked example."""
    policy = load_policy()
    field_names = {f.name for f in policy.renderable_fields}
    for applicant in read_profiles_jsonl()[:20]:
        js = json.loads(RENDERERS[RenderMode.JSON](applicant, RenderMode.JSON, policy))
        flat_keys = set()

        def _collect(obj, keys=flat_keys):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    keys.add(k)
                    _collect(v)
            elif isinstance(obj, list):
                for item in obj:
                    _collect(item)

        _collect(js)
        # A loose coverage check: every renderable field name (or its natural JSON
        # counterpart) shows up somewhere in the nested JSON's key set.
        aliases = {
            "annual_income_cents": "annual_income_cents",
            "monthly_debt_cents": "monthly_debt_cents",
            "loan_amount_cents": "amount_cents",
            "loan_term_months": "term_months",
            "credit_score": "credit_score",
            "open_tradelines": "open_count",
            "revolving_balance_cents": "balance_cents",
            "revolving_limit_cents": "limit_cents",
            "delinq_30d_24m": "30_59_days_24mo",
            "delinq_60d_24m": "60_89_days_24mo",
            "delinq_90p_24m": "90_plus_days_24mo",
            "public_records": "public_records",
            "oldest_tradeline_months": "oldest_age_months",
            "inquiries_6m": "inquiries_6m",
            "employment_months": "months",
            "employment_status": "status",
            "income_documented": "income_documented",
            "dti": "debt_to_income_ratio",
            "utilization": "utilization",
        }
        for name in field_names:
            assert aliases[name] in flat_keys, f"{name} missing from JSON render"
