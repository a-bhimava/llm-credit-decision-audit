"""Shared provider fixtures.

Request-mapping tests need a real ``ModelRequest``. Hand-building one means hand-building
a ``CreditEnvState``, which validates its applicant content id, canonical reference, and
input hash against each other. Capturing what the runner actually produces is less code
and a stronger assertion, and both adapters need the same one.
"""

from __future__ import annotations

import pytest

from credit_audit.model.client import ModelRequest

MODEL = "gemini-2.5-flash-lite"


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
