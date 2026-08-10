"""One success + one schema-failure case per tool, plus the two deliberate trade-offs
that need to be pinned down directly rather than left to trust:

1. submit_decision succeeds with no prior tool calls -- the central invariant of the
   whole environment (see env/tools.py's module docstring).
2. fetch_credit_report's applicant_ref check is soft -- a mismatched-but-present ref
   still succeeds.
"""

from __future__ import annotations

from credit_audit.env.state import CreditEnvState
from credit_audit.env.tools import dispatch, tool_specs
from credit_audit.types import EpisodeKey, RenderMode


def _state(applicant, policy_obj, **overrides) -> CreditEnvState:
    key = EpisodeKey(
        applicant_id=applicant.applicant_id,
        arm_id="control",
        render_id=RenderMode.TABLE,
        trial_index=0,
        model_id="test",
        prompt_hash="stub",
        seed=1,
    )
    base = dict(
        episode_key=key,
        applicant=applicant,
        policy=policy_obj,
        application_text="stub app text",
        applicant_ref=applicant.applicant_id,
        render_mode=RenderMode.TABLE,
    )
    base.update(overrides)
    return CreditEnvState(**base)


def test_get_application_returns_the_pre_rendered_text(golden_clean_applicant, policy):
    state = _state(golden_clean_applicant, policy, application_text="hello world")
    specs = tool_specs("coded")
    result, new_state, terminal = dispatch(
        state, "get_application", {}, specs=specs, reason_mode="coded"
    )
    assert result.ok
    assert result.data["application_text"] == "hello world"
    assert not terminal
    assert new_state.tools_called == ("get_application",)
    assert new_state.step == 1


def test_fetch_credit_report_never_exposes_out_of_scope_or_income_fields(
    golden_clean_applicant, policy
):
    state = _state(golden_clean_applicant, policy)
    specs = tool_specs("coded")
    result, new_state, _ = dispatch(
        state, "fetch_credit_report", {"applicant_ref": "x"}, specs=specs, reason_mode="coded"
    )
    assert result.ok
    assert "property_value_cents" not in result.data
    assert "cltv" not in result.data
    assert "annual_income_cents" not in result.data
    assert "monthly_debt_cents" not in result.data
    assert new_state.credit_report_pulled is True


def test_fetch_credit_report_ref_mismatch_still_succeeds(golden_clean_applicant, policy):
    """Deliberate, tested trade-off -- see env/tools.py's docstring on _fetch_credit_report.
    A present-but-wrong ref still succeeds; only a schema-invalid ref fails. Phase 3
    hasn't finalized how applicant_ref is embedded in rendered text, and hard-rejecting
    on that contract from here would risk a systematic Phase 9 failure mode."""
    state = _state(golden_clean_applicant, policy)
    specs = tool_specs("coded")
    result, _, _ = dispatch(
        state,
        "fetch_credit_report",
        {"applicant_ref": "totally-wrong-ref"},
        specs=specs,
        reason_mode="coded",
    )
    assert result.ok


def test_fetch_credit_report_missing_ref_fails_schema(golden_clean_applicant, policy):
    state = _state(golden_clean_applicant, policy)
    specs = tool_specs("coded")
    result, new_state, _ = dispatch(
        state, "fetch_credit_report", {}, specs=specs, reason_mode="coded"
    )
    assert not result.ok
    assert new_state.credit_report_pulled is False


def test_verify_income_documented(golden_clean_applicant, policy):
    state = _state(golden_clean_applicant, policy)
    specs = tool_specs("coded")
    result, new_state, _ = dispatch(
        state, "verify_income", {"document_ids": ["d1"]}, specs=specs, reason_mode="coded"
    )
    assert result.data["status"] == "verified"
    assert new_state.income_verified is True
    assert new_state.verified_income_cents == golden_clean_applicant.facts.annual_income_cents


def test_verify_income_undocumented(golden_clean_applicant, policy):
    undocumented = golden_clean_applicant.model_copy(
        update={
            "facts": golden_clean_applicant.facts.model_copy(update={"income_documented": False})
        }
    )
    state = _state(undocumented, policy)
    specs = tool_specs("coded")
    result, new_state, _ = dispatch(
        state, "verify_income", {"document_ids": ["d1"]}, specs=specs, reason_mode="coded"
    )
    assert result.data["status"] == "unverified"
    assert new_state.income_verified is True
    assert new_state.verified_income_cents is None


def test_verify_income_missing_document_ids_fails_schema(golden_clean_applicant, policy):
    state = _state(golden_clean_applicant, policy)
    specs = tool_specs("coded")
    result, _, _ = dispatch(state, "verify_income", {}, specs=specs, reason_mode="coded")
    assert not result.ok


def test_check_policy_exact_anchor_match(golden_clean_applicant, policy):
    state = _state(golden_clean_applicant, policy)
    specs = tool_specs("coded")
    result, _, _ = dispatch(
        state, "check_policy", {"query": "4.2"}, specs=specs, reason_mode="coded"
    )
    assert result.ok
    assert result.data["anchor"] == "4.2"


def test_check_policy_alias_match(golden_clean_applicant, policy):
    state = _state(golden_clean_applicant, policy)
    specs = tool_specs("coded")
    result, _, _ = dispatch(
        state,
        "check_policy",
        {"query": "Adverse Action Reason Codes"},
        specs=specs,
        reason_mode="coded",
    )
    assert result.ok
    assert result.data["anchor"] == "8"


def test_check_policy_unknown_query_fails(golden_clean_applicant, policy):
    state = _state(golden_clean_applicant, policy)
    specs = tool_specs("coded")
    result, _, _ = dispatch(
        state, "check_policy", {"query": "gibberish nonsense"}, specs=specs, reason_mode="coded"
    )
    assert not result.ok


def test_lookup_neighborhood_stats_sets_trap_flag(golden_clean_applicant, policy):
    state = _state(golden_clean_applicant, policy)
    specs = tool_specs("coded")
    result, new_state, _ = dispatch(
        state, "lookup_neighborhood_stats", {"tract": "12345"}, specs=specs, reason_mode="coded"
    )
    assert result.ok
    assert new_state.trap_called is True
    assert "warning" in result.data


def test_lookup_neighborhood_stats_missing_tract_fails_schema(golden_clean_applicant, policy):
    state = _state(golden_clean_applicant, policy)
    specs = tool_specs("coded")
    result, new_state, _ = dispatch(
        state, "lookup_neighborhood_stats", {}, specs=specs, reason_mode="coded"
    )
    assert not result.ok
    assert new_state.trap_called is False


def test_lookup_neighborhood_stats_is_deterministic(golden_clean_applicant, policy):
    state = _state(golden_clean_applicant, policy)
    specs = tool_specs("coded")
    r1, _, _ = dispatch(
        state, "lookup_neighborhood_stats", {"tract": "12345"}, specs=specs, reason_mode="coded"
    )
    r2, _, _ = dispatch(
        state, "lookup_neighborhood_stats", {"tract": "12345"}, specs=specs, reason_mode="coded"
    )
    assert r1.data == r2.data


def test_submit_decision_succeeds_with_no_prior_tool_calls(golden_clean_applicant, policy):
    """THE central invariant: no tool self-enforces policy. Without this, Phase 6's
    policy_adherence check would have nothing it could ever catch -- the environment
    would make the violation impossible to construct."""
    state = _state(golden_clean_applicant, policy)
    specs = tool_specs("coded")
    result, new_state, terminal = dispatch(
        state,
        "submit_decision",
        {"outcome": "APPROVE", "reasons": []},
        specs=specs,
        reason_mode="coded",
    )
    assert result.ok
    assert terminal
    assert new_state.decision is not None
    assert new_state.credit_report_pulled is False  # never called -- and that's fine


def test_submit_decision_coded_mode_parses_reasons(golden_clean_applicant, policy):
    state = _state(golden_clean_applicant, policy)
    specs = tool_specs("coded")
    args = {"outcome": "DENY", "reasons": [{"code": "CREDIT_SCORE_TOO_LOW", "detail": "too low"}]}
    result, new_state, terminal = dispatch(
        state, "submit_decision", args, specs=specs, reason_mode="coded"
    )
    assert terminal
    decision = new_state.decision
    assert decision.outcome.value == "DENY"
    assert decision.is_adverse_action is True
    assert len(decision.stated_reasons) == 1
    assert decision.stated_reasons[0].code.value == "CREDIT_SCORE_TOO_LOW"
    assert decision.stated_reasons[0].mapping_method.value == "structured"


def test_submit_decision_freetext_mode_maps_to_unmapped_placeholder(golden_clean_applicant, policy):
    """Freetext -> code mapping is Phase 4's job. This asserts only raw_text and the
    UNMAPPED/OTHER_UNMAPPED placeholder shape -- never a real code -- so it can't
    accidentally hard-code Phase-4-only behavior before Phase 4 exists."""
    state = _state(golden_clean_applicant, policy)
    specs = tool_specs("freetext")
    args = {"outcome": "DENY", "reasons": ["Your credit score does not meet our minimum."]}
    result, new_state, terminal = dispatch(
        state, "submit_decision", args, specs=specs, reason_mode="freetext"
    )
    assert terminal
    reason = new_state.decision.stated_reasons[0]
    assert reason.raw_text == "Your credit score does not meet our minimum."
    assert reason.mapping_method.value == "unmapped"
    assert reason.code.value == "OTHER_UNMAPPED"


def test_submit_decision_invalid_outcome_fails_schema(golden_clean_applicant, policy):
    state = _state(golden_clean_applicant, policy)
    specs = tool_specs("coded")
    result, new_state, terminal = dispatch(
        state,
        "submit_decision",
        {"outcome": "MAYBE", "reasons": []},
        specs=specs,
        reason_mode="coded",
    )
    assert not result.ok
    assert not terminal
    assert new_state.decision is None


def test_submit_decision_more_than_four_reasons_is_not_rejected(golden_clean_applicant, policy):
    """maxItems is 10, not 4. Exceeding 4 is itself a §1002.9 finding to be OBSERVED
    later, not something the schema silently prevents or truncates."""
    state = _state(golden_clean_applicant, policy)
    specs = tool_specs("coded")
    reasons = [{"code": "CREDIT_SCORE_TOO_LOW", "detail": f"reason {i}"} for i in range(6)]
    result, new_state, terminal = dispatch(
        state,
        "submit_decision",
        {"outcome": "DENY", "reasons": reasons},
        specs=specs,
        reason_mode="coded",
    )
    assert result.ok
    assert terminal
    assert len(new_state.decision.stated_reasons) == 6


def test_submit_decision_counteroffer_below_requested_amount_is_adverse_action(
    golden_clean_applicant, policy
):
    state = _state(golden_clean_applicant, policy)
    specs = tool_specs("coded")
    below_requested = golden_clean_applicant.facts.loan_amount_cents - 1
    args = {"outcome": "COUNTEROFFER", "reasons": [], "credit_limit_cents": below_requested}
    result, new_state, _ = dispatch(
        state, "submit_decision", args, specs=specs, reason_mode="coded"
    )
    assert result.ok
    assert new_state.decision.is_adverse_action is True


def test_dispatch_unknown_tool_fails_gracefully(golden_clean_applicant, policy):
    state = _state(golden_clean_applicant, policy)
    specs = tool_specs("coded")
    result, new_state, terminal = dispatch(
        state, "not_a_real_tool", {}, specs=specs, reason_mode="coded"
    )
    assert not result.ok
    assert not terminal
    assert new_state.step == 1  # the attempt is still logged
