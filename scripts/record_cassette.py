"""Record real provider responses into committed cassettes.

Reads ``GEMINI_API_KEY`` from the environment and never writes it anywhere. Every scenario
below exists to exercise a distinct path through the adapter, so the committed cassettes cover
the mapping rather than one happy case:

* ``denial``   -- a multi-breach applicant, coded reason mode. The main path, and the one that
                  produces stated reasons for the reason engine to map.
* ``freetext`` -- the other reason mode, so the lexicon tier sees real model prose rather than
                  a structured enum.
* ``truncated``-- a deliberately tiny ``max_tokens``, to record a ``length`` finish reason.
                  The runner never sets ``max_tokens``, so this one is issued at the adapter
                  boundary directly; a terminal path that only ever appears in hand-written
                  fixtures is a terminal path nobody has verified.
* ``survey``   -- several applicants at one turn each, to see how often the model actually
                  reaches ``submit_decision``. The first recording ended in prose instead of a
                  decision; one sample is an anecdote.

Spend is capped and reported. Usage:

    GEMINI_API_KEY=... python scripts/record_cassette.py [scenario ...]
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from credit_audit.checks.runner import recording_trajectories, run_trials
from credit_audit.model.cassette import Cassette, CassetteClient, CassetteMode
from credit_audit.model.providers.openai_compat import OpenAICompatClient
from credit_audit.policy.loader import load_policy
from credit_audit.policy.oracle import evaluate
from credit_audit.profiles.generate import read_profiles_jsonl
from credit_audit.run.budget import Budget, BudgetExceeded
from credit_audit.suites.loader import Caps
from credit_audit.types import DecisionOutcome, RenderMode

MODEL = "gemini-2.5-flash-lite"
PROVIDER = "gemini_openai_compat"
CASSETTE_DIR = Path("tests/fixtures/cassettes/gemini_flash_lite")
MAX_USD = float(os.environ.get("MAX_USD", "0.10"))


def _client(cassette: Cassette, api_key: str) -> CassetteClient:
    return CassetteClient(
        OpenAICompatClient(MODEL, api_key=api_key, provider=PROVIDER),
        cassette,
        mode=CassetteMode.REPLAY_OR_RECORD,
        provider=PROVIDER,
    )


def _report(label: str, trajectory) -> None:
    decision = trajectory.decision
    print(f"  [{label}] termination={trajectory.termination.value}")
    print(f"      tools    : {[c.name for c in trajectory.tool_calls]}")
    print(f"      decision : {decision.outcome.value if decision else None}")
    if decision:
        print(f"      reasons  : {[r.code.value for r in decision.stated_reasons]}")
        print(f"      mapping  : {[r.mapping_method.value for r in decision.stated_reasons]}")
    print(f"      signature: {bool(trajectory.provider_state)}")


def main(argv: list[str]) -> int:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return int(bool(sys.stderr.write("GEMINI_API_KEY is not set\n"))) or 2

    wanted = set(argv) or {"denial", "freetext", "truncated", "survey"}
    policy = load_policy()
    profiles = sorted(read_profiles_jsonl(), key=lambda a: a.applicant_id)
    multi_breach = [
        a
        for a in profiles
        if evaluate(a.facts, policy).outcome is not DecisionOutcome.APPROVE
        and len(set(evaluate(a.facts, policy).breached_codes)) >= 2
    ]

    cassette = Cassette(CASSETTE_DIR)
    client = _client(cassette, api_key)
    budget = Budget(Caps(max_usd=MAX_USD, max_episodes=40))
    captured: list = []

    def sink(trajectory, _applicant):
        captured.append(trajectory)
        budget.charge(trajectory)

    try:
        with recording_trajectories(sink):
            if "denial" in wanted:
                print("\n== denial (coded), multi-breach applicant")
                before = len(captured)
                asyncio.run(_episode(client, multi_breach[0], policy, "coded", "denial"))
                for trajectory in captured[before:]:
                    _report(multi_breach[0].applicant_id, trajectory)

            if "freetext" in wanted:
                print("\n== freetext reason mode")
                before = len(captured)
                asyncio.run(_episode(client, multi_breach[0], policy, "freetext", "freetext"))
                for trajectory in captured[before:]:
                    _report("freetext", trajectory)

            if "survey" in wanted:
                print("\n== survey: does the model reach submit_decision?")
                for applicant in multi_breach[1:5]:
                    before = len(captured)
                    asyncio.run(_episode(client, applicant, policy, "coded", "survey"))
                    for trajectory in captured[before:]:
                        _report(applicant.applicant_id, trajectory)
    except BudgetExceeded as exceeded:
        print(f"\nBUDGET STOP: {exceeded}")

    if "truncated" in wanted:
        print("\n== truncated: a `length` finish reason at the adapter boundary")
        asyncio.run(_truncated(client, multi_breach[0], policy))

    reached = sum(1 for t in captured if t.decision is not None)
    print(f"\nreached submit_decision: {reached}/{len(captured)} episodes")
    print(f"any thought signature  : {any(bool(t.provider_state) for t in captured)}")
    print(f"spent ${budget.state().usd:.6f} of ${MAX_USD}")
    print(f"cassette records       : {len(cassette.entries())}")
    return 0


async def _episode(client, applicant, policy, reason_mode, seed_group):
    await run_trials(
        applicant=applicant,
        client=client,
        policy=policy,
        render_mode=RenderMode.TABLE,
        run_seed=1729,
        seed_group=f"cassette-{seed_group}",
        arm_id=f"cassette-{seed_group}",
        k_trials=1,
        reason_mode=reason_mode,
    )


async def _truncated(client, applicant, policy) -> None:
    """Capture a real request, then re-issue it with a tiny cap to force `length`."""

    captured: list = []

    class _Capture:
        model_id = MODEL

        async def complete(self, req):
            from credit_audit.model.client import ModelResponse

            captured.append(req)
            return ModelResponse(content="", stop_reason="stop")

    await run_trials(
        applicant=applicant,
        client=_Capture(),
        policy=policy,
        render_mode=RenderMode.TABLE,
        run_seed=1729,
        seed_group="cassette-truncated",
        arm_id="cassette-truncated",
        k_trials=1,
    )
    response = await client.complete(captured[0].model_copy(update={"max_tokens": 4}))
    print(f"  stop_reason={response.stop_reason} out_tokens={response.usage.output_tokens}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
