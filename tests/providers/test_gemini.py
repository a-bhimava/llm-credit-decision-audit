"""The native adapter: a different wire shape, the same provider-neutral record.

Its reason for existing is `cached_content_token_count`, so the telemetry assertions matter
more here than the mapping ones. Nothing touches a network.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from credit_audit.model.providers.gemini import (
    GeminiClient,
    finish_reason_to_stop_reason,
    messages_to_contents,
    response_from_gemini,
    tool_to_gemini,
)
from credit_audit.types import FrozenDict, Message, RequestedToolCall

MODEL = "gemini-2.5-flash-lite"


def _part(*, text=None, call=None, signature=None):
    return SimpleNamespace(text=text, function_call=call, thought_signature=signature)


def _response(*, parts=(), finish="STOP", usage=None):
    return SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(parts=list(parts)),
                finish_reason=SimpleNamespace(name=finish),
            )
        ],
        usage_metadata=usage,
    )


# --------------------------------------------------------------------------------------
# The number this adapter exists for
# --------------------------------------------------------------------------------------


def test_cached_token_count_is_read_from_provider_usage():
    """Measured, never asserted. The shared prefix is around a thousand tokens, below every
    published implicit-cache minimum, so assuming a hit would almost certainly be wrong."""

    usage = SimpleNamespace(
        prompt_token_count=8000,
        candidates_token_count=50,
        cached_content_token_count=6000,
        thoughts_token_count=0,
    )
    response = response_from_gemini(
        _response(parts=[_part(text="ok")], usage=usage), model_id=MODEL
    )
    assert response.usage.cached_tokens == 6000
    assert response.usage.cache_hit is True


def test_no_cache_hit_is_reported_as_zero_not_omitted():
    usage = SimpleNamespace(
        prompt_token_count=8000,
        candidates_token_count=50,
        cached_content_token_count=0,
        thoughts_token_count=0,
    )
    response = response_from_gemini(
        _response(parts=[_part(text="ok")], usage=usage), model_id=MODEL
    )
    assert response.usage.cached_tokens == 0
    assert response.usage.cache_hit is False


def test_thinking_tokens_are_captured_separately():
    usage = SimpleNamespace(
        prompt_token_count=10,
        candidates_token_count=5,
        cached_content_token_count=0,
        thoughts_token_count=99,
    )
    response = response_from_gemini(_response(parts=[_part(text="x")], usage=usage), model_id=MODEL)
    assert response.usage.thought_tokens == 99


def test_a_missing_usage_block_does_not_break_the_mapping():
    response = response_from_gemini(_response(parts=[_part(text="x")]), model_id=MODEL)
    assert response.usage.input_tokens == 0
    assert response.usage.cost_usd == 0.0


# --------------------------------------------------------------------------------------
# Shape differences from the compat path
# --------------------------------------------------------------------------------------


def test_a_tool_result_becomes_a_function_response_on_a_user_turn():
    """Gemini has no `tool` role; a result is a function_response part from the user."""

    contents = messages_to_contents(
        (Message(role="tool", content='{"ok": true}', step=0, tool_call_id="get_application"),),
        FrozenDict({}),
    )
    assert contents[0]["role"] == "user"
    response = contents[0]["parts"][0]["function_response"]
    assert response["name"] == "get_application"
    assert response["response"] == {"ok": True}


def test_a_non_object_tool_result_is_wrapped_rather_than_dropped():
    contents = messages_to_contents(
        (Message(role="tool", content="plain text", step=0, tool_call_id="t"),), FrozenDict({})
    )
    assert contents[0]["parts"][0]["function_response"]["response"] == {"result": "plain text"}


def test_the_assistant_role_becomes_model():
    contents = messages_to_contents(
        (Message(role="assistant", content="hello", step=0),), FrozenDict({})
    )
    assert contents[0]["role"] == "model"


def test_the_system_prompt_travels_on_the_config_not_in_the_history():
    """Repeating it as a turn would send it twice and inflate every prompt."""

    contents = messages_to_contents(
        (Message(role="system", content="SYS", step=0), Message(role="user", content="hi", step=0)),
        FrozenDict({}),
    )
    assert len(contents) == 1
    assert contents[0]["role"] == "user"


def test_a_signature_is_attached_to_the_part_not_the_call():
    """The shape difference that would silently break a copied compat implementation."""

    messages = (
        Message(
            role="assistant",
            content="",
            step=0,
            tool_calls=(
                RequestedToolCall(call_id="c1", name="get_application", arguments=FrozenDict({})),
            ),
        ),
    )
    contents = messages_to_contents(messages, FrozenDict({"c1": "SIG=="}))
    part = contents[0]["parts"][0]
    assert part["thought_signature"] == "SIG=="
    assert "thought_signature" not in part["function_call"]


def test_a_returned_signature_is_captured_from_the_part():
    call = SimpleNamespace(id="c1", name="get_application", args={"a": 1})
    response = response_from_gemini(
        _response(parts=[_part(call=call, signature="SIG==")], finish="STOP"), model_id=MODEL
    )
    assert response.provider_state["c1"] == "SIG=="
    assert response.tool_calls[0].arguments["a"] == 1


def test_a_bytes_signature_is_normalised_to_one_storable_shape():
    call = SimpleNamespace(id="c1", name="t", args={})
    response = response_from_gemini(
        _response(parts=[_part(call=call, signature=b"\x01\x02")]), model_id=MODEL
    )
    assert isinstance(response.provider_state["c1"], str)


# --------------------------------------------------------------------------------------
# Finish reasons and config
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("finish", "expected"),
    [("STOP", "stop"), ("MAX_TOKENS", "max_tokens"), ("SAFETY", "refusal"), ("WEIRD", "error")],
)
def test_finish_reasons_map_to_the_runner_vocabulary(finish, expected):
    assert (
        finish_reason_to_stop_reason(SimpleNamespace(name=finish), has_tool_calls=False) == expected
    )


def test_a_tool_call_outranks_a_reported_stop():
    """Gemini reports STOP alongside function calls; believing it ends the episode early."""

    assert (
        finish_reason_to_stop_reason(SimpleNamespace(name="STOP"), has_tool_calls=True)
        == "tool_calls"
    )


def test_tool_specs_become_function_declarations():
    from credit_audit.env.tools import tool_specs

    spec = tool_specs("coded")[0]
    declaration = tool_to_gemini(spec)
    assert declaration["name"] == spec.name
    assert isinstance(declaration["parameters"], dict)


def test_unset_parameters_are_omitted_from_the_config(captured_request):
    client = GeminiClient(MODEL, api_key="unused", transport=object())
    config = client.build_config(captured_request)
    assert config["system_instruction"] == captured_request.system
    assert "temperature" not in config
    assert "max_output_tokens" not in config
    names = {d["name"] for d in config["tools"][0]["function_declarations"]}
    assert {"get_application", "submit_decision"} <= names


def test_set_parameters_reach_the_config(captured_request):
    client = GeminiClient(MODEL, api_key="unused", transport=object())
    config = client.build_config(
        captured_request.model_copy(update={"temperature": 0.0, "max_tokens": 32})
    )
    assert config["temperature"] == 0.0
    assert config["max_output_tokens"] == 32
