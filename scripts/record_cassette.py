"""One-off recorder: a single real episode against gemini-2.5-flash-lite.

Deliberately small. The question this answers is whether the adapter's mapping survives
contact with real bytes -- and whether flash-lite with thinking off emits a thought signature
at all, which decides how load-bearing the passthrough really is.
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
from credit_audit.profiles.generate import read_profiles_jsonl
from credit_audit.run.budget import Budget, BudgetExceeded
from credit_audit.suites.loader import Caps
from credit_audit.types import RenderMode

MODEL = "gemini-2.5-flash-lite"
MAX_USD = float(os.environ.get("MAX_USD", "0.05"))

key = os.environ.get("GEMINI_API_KEY")
if not key:
    sys.exit("GEMINI_API_KEY is not set")

policy = load_policy()
applicant = sorted(read_profiles_jsonl(), key=lambda a: a.applicant_id)[0]

cassette = Cassette(Path("tests/fixtures/cassettes/gemini_flash_lite"))
client = CassetteClient(
    OpenAICompatClient(MODEL, api_key=key, provider="gemini_openai_compat"),
    cassette,
    mode=CassetteMode.REPLAY_OR_RECORD,
    provider="gemini_openai_compat",
)

budget = Budget(Caps(max_usd=MAX_USD, max_episodes=4))
trajectories = []


def sink(trajectory, _applicant):
    trajectories.append(trajectory)
    budget.charge(trajectory)


try:
    with recording_trajectories(sink):
        asyncio.run(
            run_trials(
                applicant=applicant,
                client=client,
                policy=policy,
                render_mode=RenderMode.TABLE,
                run_seed=1729,
                seed_group="cassette-record",
                arm_id="cassette-record",
                k_trials=1,
            )
        )
except BudgetExceeded as exceeded:
    print(f"BUDGET STOP: {exceeded}")

for trajectory in trajectories:
    print(f"\ntermination : {trajectory.termination.value}")
    print(f"tool calls  : {[c.name for c in trajectory.tool_calls]}")
    print(f"decision    : {trajectory.decision.outcome.value if trajectory.decision else None}")
    if trajectory.decision:
        print(f"reasons     : {[r.code.value for r in trajectory.decision.stated_reasons]}")
    usage = trajectory.usage
    print(f"tokens      : in={usage.input_tokens} out={usage.output_tokens}")
    print(f"cost        : ${usage.cost_usd:.6f}")
    print(f"THOUGHT SIGNATURES PRESENT: {bool(trajectory.provider_state)}")
    if trajectory.provider_state:
        print(f"  keys: {sorted(trajectory.provider_state)}")

print(f"\nspent ${budget.state().usd:.6f} of ${MAX_USD}")
print(f"cassette records: {len(cassette.entries())}")
