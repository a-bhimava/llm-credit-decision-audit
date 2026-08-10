"""render_stub (tests/conftest.py) must never leak an out-of-scope field. This is the
property that makes OutOfSchemaAgent's canonical "insufficient collateral" example
meaningful: the agent must never have actually been shown a collateral field, or a
sharp reviewer could argue the citation was grounded in what it was shown.
"""

from __future__ import annotations

from credit_audit.types import RenderMode


def test_render_stub_never_leaks_out_of_scope_fields(golden_clean_applicant, policy, render_stub):
    for mode in (RenderMode.TABLE, RenderMode.PROSE, RenderMode.JSON):
        text = render_stub(golden_clean_applicant, mode, policy).lower()
        assert "property_value" not in text
        assert "collateral" not in text
        assert "cltv" not in text
        assert "loan-to-value" not in text


def test_render_stub_shows_in_scope_fields(golden_clean_applicant, policy, render_stub):
    text = render_stub(golden_clean_applicant, RenderMode.TABLE, policy).lower()
    assert "credit score" in text
    assert "annual income" in text
