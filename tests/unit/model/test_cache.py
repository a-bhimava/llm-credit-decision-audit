"""Cache-key stability, episode-context isolation, atomic writes, and replay telemetry."""

from __future__ import annotations

import asyncio

from credit_audit.env.state import CreditEnvState
from credit_audit.env.tools import tool_specs
from credit_audit.ids import applicant_content_id, content_id, episode_input_hash
from credit_audit.model.cache import CachedClient, ResponseCache, cache_key
from credit_audit.model.client import ModelRequest, ModelResponse
from credit_audit.render.reference import applicant_reference_for
from credit_audit.types import EpisodeKey, RenderMode, Usage


def _request(applicant, policy_obj, *, seed=1) -> ModelRequest:
    applicant_ref = applicant_reference_for(applicant)
    application_text = "stub"
    key = EpisodeKey(
        applicant_id=applicant.applicant_id,
        applicant_content_id=applicant_content_id(applicant),
        arm_id="control",
        render_id=RenderMode.TABLE,
        trial_index=0,
        model_id="test",
        prompt_hash="stub",
        input_hash=episode_input_hash(
            applicant,
            application_text=application_text,
            applicant_ref=applicant_ref,
            render_mode=RenderMode.TABLE,
        ),
        seed=seed,
    )
    state = CreditEnvState(
        episode_key=key,
        applicant=applicant,
        policy=policy_obj,
        application_text=application_text,
        applicant_ref=applicant_ref,
        render_mode=RenderMode.TABLE,
    )
    return ModelRequest(
        model_id="test",
        system="sys",
        messages=(),
        tools=tool_specs("coded"),
        temperature=None,
        top_p=None,
        max_tokens=None,
        seed=seed,
        context_hash=content_id({"applicant": applicant, "application_text": "stub"}),
        env_state=state,
    )


def _key_for(req: ModelRequest, **param_overrides) -> str:
    params = {"seed": req.seed}
    params.update(param_overrides)
    return cache_key(
        provider="test",
        model_id=req.model_id,
        params=params,
        system=req.system,
        messages=req.messages,
        tools=req.tools,
        context_hash=req.context_hash,
    )


def test_cache_key_stable_for_identical_requests(golden_clean_applicant, policy):
    r1 = _request(golden_clean_applicant, policy)
    r2 = _request(golden_clean_applicant, policy)
    assert _key_for(r1) == _key_for(r2)


def test_cache_key_changes_with_system(golden_clean_applicant, policy):
    r = _request(golden_clean_applicant, policy)
    k1 = cache_key(
        provider="test",
        model_id=r.model_id,
        params={"seed": r.seed},
        system="A",
        messages=r.messages,
        tools=r.tools,
        context_hash=r.context_hash,
    )
    k2 = cache_key(
        provider="test",
        model_id=r.model_id,
        params={"seed": r.seed},
        system="B",
        messages=r.messages,
        tools=r.tools,
        context_hash=r.context_hash,
    )
    assert k1 != k2


def test_cache_key_includes_seed(golden_clean_applicant, policy):
    r1 = _request(golden_clean_applicant, policy, seed=1)
    r2 = _request(golden_clean_applicant, policy, seed=2)
    assert _key_for(r1) != _key_for(r2)


def test_cache_key_isolates_first_turn_applicant_context(
    golden_clean_applicant, multi_breach_applicant, policy
):
    r1 = _request(golden_clean_applicant, policy)
    r2 = _request(multi_breach_applicant, policy)
    assert r1.env_state != r2.env_state
    assert _key_for(r1) != _key_for(r2)


def test_response_cache_roundtrip(tmp_path):
    cache = ResponseCache(tmp_path)
    resp = ModelResponse(content="hello", stop_reason="stop")
    cache.put("blake2b128:deadbeef", resp)
    loaded = cache.get("blake2b128:deadbeef")
    assert loaded is not None
    assert loaded.content == "hello"
    assert loaded.stop_reason == "stop"


def test_response_cache_miss_returns_none(tmp_path):
    cache = ResponseCache(tmp_path)
    assert cache.get("blake2b128:doesnotexist") is None


class _OnceClient:
    model_id = "test:once"

    def __init__(self):
        self.calls = 0

    async def complete(self, _req):
        self.calls += 1
        return ModelResponse(
            content="answer",
            stop_reason="stop",
            usage=Usage(
                input_tokens=10,
                output_tokens=2,
                cached_tokens=3,
                thought_tokens=4,
                cost_usd=0.1,
            ),
        )


def test_cached_client_replays_on_second_call(tmp_path, golden_clean_applicant, policy):
    cache = ResponseCache(tmp_path)
    inner = _OnceClient()
    client = CachedClient(inner, cache, provider="test")
    req = _request(golden_clean_applicant, policy)

    r1 = asyncio.run(client.complete(req))
    r2 = asyncio.run(client.complete(req))

    assert inner.calls == 1
    assert r1.usage.replayed is False
    assert r2.usage.replayed is True
    assert r2.usage.cache_hit is True
    assert r2.usage.cost_usd == 0.0
    assert r2.usage.cached_tokens == 3
    assert r2.usage.thought_tokens == 4
    assert r1.content == r2.content == "answer"
