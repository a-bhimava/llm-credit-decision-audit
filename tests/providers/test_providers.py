"""The provider seam: request mapping, response mapping, and the guarantees around them.

No test here touches a network or needs a credential. The adapter takes an injected transport,
so what is asserted is the exact payload it would have sent and the record it builds from what
came back.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from credit_audit.model.client import ModelRequest
from credit_audit.model.providers.openai_compat import (
    GOOGLE_SIGNATURE_KEY,
    OpenAICompatClient,
    finish_reason_to_stop_reason,
    messages_to_openai,
    response_from_openai,
    tool_to_openai,
)
from credit_audit.model.providers.pricing import PRICES, cost_usd, price_for
from credit_audit.types import FrozenDict, Message, RequestedToolCall

MODEL = "gemini-2.5-flash-lite"


# --------------------------------------------------------------------------------------
# Pricing
# --------------------------------------------------------------------------------------


def test_cost_is_computed_from_returned_usage():
    cost, priced = cost_usd(MODEL, input_tokens=1_000_000, output_tokens=1_000_000)
    assert priced is True
    assert cost == pytest.approx(0.10 + 0.40)


def test_a_dated_snapshot_inherits_its_base_price():
    """Providers publish ids like `<model>-preview-09-2025`; a snapshot is not free."""

    assert price_for(f"{MODEL}-preview-09-2025") is PRICES[MODEL]


def test_an_unpriced_model_is_flagged_rather_than_assumed_free():
    """Silently pricing an unknown model at zero would make every budget cap pass."""

    cost, priced = cost_usd("not-a-real-model", input_tokens=10**6, output_tokens=10**6)
    assert cost == 0.0
    assert priced is False


def test_cached_tokens_are_a_subset_of_input_not_an_addition():
    """Both OpenAI and Gemini report cached tokens as part of the prompt, not beside it."""

    plain, _ = cost_usd(MODEL, input_tokens=1_000_000, output_tokens=0)
    cached, _ = cost_usd(MODEL, input_tokens=1_000_000, output_tokens=0, cached_tokens=1_000_000)
    assert cached <= plain


# --------------------------------------------------------------------------------------
# Finish reasons
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("finish", "expected"),
    [("stop", "stop"), ("length", "max_tokens"), ("content_filter", "refusal"), (None, "stop")],
)
def test_finish_reasons_map_to_the_runner_vocabulary(finish, expected):
    assert finish_reason_to_stop_reason(finish, has_tool_calls=False) == expected


def test_tool_calls_win_over_a_reported_stop():
    """Some endpoints send `stop` alongside populated tool_calls; believing it truncates the
    episode a turn early and the decision never gets submitted."""

    assert finish_reason_to_stop_reason("stop", has_tool_calls=True) == "tool_calls"


def test_an_unrecognised_finish_reason_is_an_error_not_a_silent_stop():
    assert finish_reason_to_stop_reason("something_new", has_tool_calls=False) == "error"


# --------------------------------------------------------------------------------------
# Request mapping
# --------------------------------------------------------------------------------------


class _CapturingClient:
    """Records the request the runner builds, then terminates the episode immediately.

    Hand-building a `ModelRequest` means hand-building a `CreditEnvState`, which validates
    its own applicant content id, canonical reference, and input hash against each other.
    Capturing the real thing is less code and a stronger test: it asserts against the request
    the runner actually produces, not one a test author imagined.
    """

    model_id = MODEL

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    async def complete(self, req: ModelRequest):
        from credit_audit.model.client import ModelResponse

        self.requests.append(req)
        return ModelResponse(content="stopping", stop_reason="stop")


@pytest.fixture(scope="module")
def captured_request(policy, golden_clean_applicant) -> ModelRequest:
    import asyncio

    from credit_audit.checks.runner import run_trials

    client = _CapturingClient()
    asyncio.run(
        run_trials(
            applicant=golden_clean_applicant,
            client=client,
            policy=policy,
            render_mode=__import__("credit_audit.types", fromlist=["RenderMode"]).RenderMode.TABLE,
            run_seed=1729,
            seed_group="provider-test",
            arm_id="provider-test",
            k_trials=1,
        )
    )
    assert client.requests, "the runner must have issued at least one request"
    return client.requests[0]


def test_tool_specs_pass_through_as_json_schema():
    from credit_audit.env.tools import tool_specs

    spec = tool_specs("coded")[0]
    wire = tool_to_openai(spec)
    assert wire["type"] == "function"
    assert wire["function"]["name"] == spec.name
    assert isinstance(wire["function"]["parameters"], dict)


def test_unset_generation_parameters_are_omitted_entirely(captured_request):
    """A compat endpoint may reject a field it does not know, so nothing is sent by default."""

    client = OpenAICompatClient(MODEL, api_key="unused", transport=object())
    payload = client.build_payload(captured_request)
    assert "temperature" not in payload
    assert "top_p" not in payload
    assert "max_tokens" not in payload
    assert payload["model"] == MODEL
    assert payload["tool_choice"] == "auto"


def test_set_parameters_are_sent(captured_request):
    client = OpenAICompatClient(MODEL, api_key="unused", transport=object())
    payload = client.build_payload(
        captured_request.model_copy(update={"temperature": 0.0, "max_tokens": 256})
    )
    assert payload["temperature"] == 0.0
    assert payload["max_tokens"] == 256


def test_the_system_prompt_is_sent_once_as_a_system_message(captured_request):
    """The trajectory keeps a system-role Message as evidence; the wire must not repeat it."""

    client = OpenAICompatClient(MODEL, api_key="unused", transport=object())
    payload = client.build_payload(captured_request)
    systems = [m for m in payload["messages"] if m["role"] == "system"]
    assert len(systems) == 1
    assert systems[0]["content"] == captured_request.system


def test_the_captured_request_carries_the_real_tool_suite(captured_request):
    payload = OpenAICompatClient(MODEL, api_key="unused", transport=object()).build_payload(
        captured_request
    )
    names = {tool["function"]["name"] for tool in payload["tools"]}
    assert {"get_application", "fetch_credit_report", "submit_decision"} <= names


# --------------------------------------------------------------------------------------
# Provider state: the thought-signature round trip
# --------------------------------------------------------------------------------------


def test_a_signature_is_reattached_verbatim_on_the_next_turn():
    """The property whose absence is a hard 400 on a thinking model."""

    signature = "Cr0BAdHtim9-OPAQUE-SIGNATURE-BYTES=="
    messages = (
        Message(
            role="assistant",
            content="",
            step=0,
            tool_calls=(
                RequestedToolCall(
                    call_id="call_1", name="get_application", arguments=FrozenDict({})
                ),
            ),
        ),
        Message(role="tool", content="{}", step=0, tool_call_id="call_1"),
    )
    wire = messages_to_openai("SYS", messages, FrozenDict({"call_1": signature}))
    assistant = next(m for m in wire if m["role"] == "assistant")
    extra = assistant["tool_calls"][0]["extra_content"]
    assert extra["google"][GOOGLE_SIGNATURE_KEY] == signature, "must be byte-identical"


def test_no_signature_means_no_extra_content_field():
    """Sending an empty container to a provider that never asked for one invites a 400."""

    messages = (
        Message(
            role="assistant",
            content="",
            step=0,
            tool_calls=(RequestedToolCall(call_id="call_1", name="t", arguments=FrozenDict({})),),
        ),
    )
    wire = messages_to_openai("SYS", messages, FrozenDict({}))
    assert "extra_content" not in wire[-1]["tool_calls"][0]


def test_a_signature_for_a_different_call_is_not_misattached():
    messages = (
        Message(
            role="assistant",
            content="",
            step=0,
            tool_calls=(RequestedToolCall(call_id="call_a", name="t", arguments=FrozenDict({})),),
        ),
    )
    wire = messages_to_openai("SYS", messages, FrozenDict({"call_b": "sig"}))
    assert "extra_content" not in wire[-1]["tool_calls"][0]


def test_tool_arguments_round_trip_as_a_json_string():
    messages = (
        Message(
            role="assistant",
            content="",
            step=0,
            tool_calls=(
                RequestedToolCall(
                    call_id="c", name="t", arguments=FrozenDict({"applicant_ref": "MPL-1"})
                ),
            ),
        ),
    )
    wire = messages_to_openai("SYS", messages, FrozenDict({}))
    raw = wire[-1]["tool_calls"][0]["function"]["arguments"]
    assert json.loads(raw) == {"applicant_ref": "MPL-1"}


# --------------------------------------------------------------------------------------
# Response mapping
# --------------------------------------------------------------------------------------


def _completion(*, tool_calls=(), content=None, finish="stop", usage=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=finish,
                message=SimpleNamespace(content=content, tool_calls=list(tool_calls)),
            )
        ],
        usage=usage,
    )


def _wire_call(call_id, name, arguments, signature=None):
    extra = {"google": {GOOGLE_SIGNATURE_KEY: signature}} if signature else None
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
        extra_content=extra,
    )


def test_a_returned_signature_is_captured_into_provider_state():
    response = response_from_openai(
        _completion(
            tool_calls=[_wire_call("call_1", "get_application", {}, signature="SIG==")],
            finish="tool_calls",
        ),
        model_id=MODEL,
    )
    assert response.provider_state["call_1"] == "SIG=="
    assert response.stop_reason == "tool_calls"
    assert response.tool_calls[0].name == "get_application"


def test_usage_and_cost_come_from_the_response_not_the_request():
    usage = SimpleNamespace(
        prompt_tokens=1_000_000,
        completion_tokens=1_000_000,
        prompt_tokens_details=SimpleNamespace(cached_tokens=0),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=11),
    )
    response = response_from_openai(_completion(content="hi", usage=usage), model_id=MODEL)
    assert response.usage.input_tokens == 1_000_000
    assert response.usage.thought_tokens == 11
    assert response.usage.cost_usd == pytest.approx(0.5)


def test_cached_tokens_set_the_cache_hit_flag():
    usage = SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=1,
        prompt_tokens_details=SimpleNamespace(cached_tokens=40),
        completion_tokens_details=None,
    )
    response = response_from_openai(_completion(content="x", usage=usage), model_id=MODEL)
    assert response.usage.cached_tokens == 40
    assert response.usage.cache_hit is True


def test_an_unpriced_model_marks_itself_in_provider_state():
    """So a run against an unpriced model cannot quietly report a zero cost as measured."""

    response = response_from_openai(_completion(content="x"), model_id="unknown-model")
    assert response.provider_state["__unpriced_model__"] == "unknown-model"


def test_malformed_tool_arguments_become_evidence_rather_than_a_crash():
    call = SimpleNamespace(
        id="c",
        function=SimpleNamespace(name="t", arguments="{not json"),
        extra_content=None,
    )
    response = response_from_openai(
        _completion(tool_calls=[call], finish="tool_calls"), model_id=MODEL
    )
    assert response.tool_calls[0].arguments["__unparsed_arguments__"] == "{not json"


def test_a_missing_usage_block_does_not_break_the_mapping():
    response = response_from_openai(_completion(content="x", usage=None), model_id=MODEL)
    assert response.usage.input_tokens == 0
    assert response.usage.cost_usd == 0.0
