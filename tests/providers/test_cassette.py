"""Record and replay at the protocol boundary.

These tests exist to be written *before* the first real recording. A cassette reader that is
only exercised by cassettes it wrote itself agrees with itself by construction; the failures
worth catching are a replay silently falling through to the network, a record standing in for
a different model, and a credential reaching disk.

Nothing here touches a network. The inner client is a counting stub, so "did this call the
provider" is a directly observable fact rather than an inference.
"""

from __future__ import annotations

import asyncio
import gzip

import pytest

from credit_audit.model.cassette import (
    Cassette,
    CassetteClient,
    CassetteEntry,
    CassetteMiss,
    CassetteMode,
    request_params,
)
from credit_audit.model.client import ModelRequest, ModelResponse
from credit_audit.report.bundle import ExportError
from credit_audit.types import FrozenDict, Usage

MODEL = "gemini-2.5-flash-lite"


class _CountingClient:
    """An inner client that reports how many times it was actually called."""

    def __init__(self, model_id: str = MODEL, response: ModelResponse | None = None) -> None:
        self.model_id = model_id
        self.calls = 0
        self._response = response or ModelResponse(
            content="live answer",
            stop_reason="stop",
            usage=Usage(input_tokens=100, output_tokens=10, cost_usd=0.25),
            provider_state=FrozenDict({"call_1": "SIGNATURE=="}),
        )

    async def complete(self, _req: ModelRequest) -> ModelResponse:
        self.calls += 1
        return self._response


@pytest.fixture(scope="module")
def request_fixture(policy, golden_clean_applicant) -> ModelRequest:
    """A real ModelRequest captured from the runner, for the same reason as elsewhere:
    CreditEnvState validates its own identities against each other."""

    from credit_audit.checks.runner import run_trials
    from credit_audit.types import RenderMode

    captured: list[ModelRequest] = []

    class _Capture:
        model_id = MODEL

        async def complete(self, req: ModelRequest) -> ModelResponse:
            captured.append(req)
            return ModelResponse(content="", stop_reason="stop")

    asyncio.run(
        run_trials(
            applicant=golden_clean_applicant,
            client=_Capture(),
            policy=policy,
            render_mode=RenderMode.TABLE,
            run_seed=1729,
            seed_group="cassette-test",
            arm_id="cassette-test",
            k_trials=1,
        )
    )
    return captured[0]


def _client(tmp_path, mode, inner=None) -> tuple[CassetteClient, _CountingClient, Cassette]:
    cassette = Cassette(tmp_path / "cassette")
    stub = inner or _CountingClient()
    return (
        CassetteClient(stub, cassette, mode=mode, now=lambda: "2026-01-01T00:00:00+00:00"),
        stub,
        cassette,
    )


# --------------------------------------------------------------------------------------
# Modes
# --------------------------------------------------------------------------------------


def test_off_passes_through_and_records_nothing(tmp_path, request_fixture):
    client, inner, cassette = _client(tmp_path, CassetteMode.OFF)
    response = asyncio.run(client.complete(request_fixture))

    assert inner.calls == 1
    assert response.content == "live answer"
    assert cassette.entries() == ()


def test_record_calls_the_provider_and_writes(tmp_path, request_fixture):
    client, inner, cassette = _client(tmp_path, CassetteMode.RECORD)
    asyncio.run(client.complete(request_fixture))

    assert inner.calls == 1
    entries = cassette.entries()
    assert len(entries) == 1
    assert entries[0].model_id == MODEL
    assert entries[0].response.content == "live answer"


def test_record_overwrites_rather_than_serving_a_stale_record(tmp_path, request_fixture):
    """Record mode means record. Serving the old value would make re-recording a no-op."""

    client, inner, _ = _client(tmp_path, CassetteMode.RECORD)
    asyncio.run(client.complete(request_fixture))
    asyncio.run(client.complete(request_fixture))
    assert inner.calls == 2


def test_replay_never_calls_the_provider(tmp_path, request_fixture):
    """The property that keeps CI free. A silent fallthrough would bill you unobserved."""

    recorder, inner, cassette = _client(tmp_path, CassetteMode.RECORD)
    asyncio.run(recorder.complete(request_fixture))
    assert inner.calls == 1

    replayer = CassetteClient(inner, cassette, mode=CassetteMode.REPLAY)
    response = asyncio.run(replayer.complete(request_fixture))

    assert inner.calls == 1, "replay must not reach the provider"
    assert response.content == "live answer"


def test_a_replay_miss_is_fatal_rather_than_a_live_call(tmp_path, request_fixture):
    client, inner, _ = _client(tmp_path, CassetteMode.REPLAY)
    with pytest.raises(CassetteMiss, match="never calls the provider"):
        asyncio.run(client.complete(request_fixture))
    assert inner.calls == 0


def test_replay_or_record_fills_a_gap_then_replays_it(tmp_path, request_fixture):
    client, inner, _ = _client(tmp_path, CassetteMode.REPLAY_OR_RECORD)
    asyncio.run(client.complete(request_fixture))
    asyncio.run(client.complete(request_fixture))
    assert inner.calls == 1, "the second call must come from the cassette"


# --------------------------------------------------------------------------------------
# What a replayed response reports
# --------------------------------------------------------------------------------------


def test_a_replayed_response_costs_nothing_and_says_so(tmp_path, request_fixture):
    """`current_run_cost` in the manifest depends on this being honest."""

    recorder, inner, cassette = _client(tmp_path, CassetteMode.RECORD)
    live = asyncio.run(recorder.complete(request_fixture))
    assert live.usage.cost_usd == 0.25
    assert live.usage.replayed is False

    replayed = asyncio.run(
        CassetteClient(inner, cassette, mode=CassetteMode.REPLAY).complete(request_fixture)
    )
    assert replayed.usage.replayed is True
    assert replayed.usage.cost_usd == 0.0


def test_replay_preserves_provider_state_verbatim(tmp_path, request_fixture):
    """A cassette that dropped the signature would replay a conversation the provider
    would have rejected, which is the opposite of a faithful recording."""

    recorder, inner, cassette = _client(tmp_path, CassetteMode.RECORD)
    asyncio.run(recorder.complete(request_fixture))
    replayed = asyncio.run(
        CassetteClient(inner, cassette, mode=CassetteMode.REPLAY).complete(request_fixture)
    )
    assert replayed.provider_state["call_1"] == "SIGNATURE=="


def test_token_counts_survive_replay_even_though_cost_does_not(tmp_path, request_fixture):
    recorder, inner, cassette = _client(tmp_path, CassetteMode.RECORD)
    asyncio.run(recorder.complete(request_fixture))
    replayed = asyncio.run(
        CassetteClient(inner, cassette, mode=CassetteMode.REPLAY).complete(request_fixture)
    )
    assert replayed.usage.input_tokens == 100
    assert replayed.usage.output_tokens == 10


# --------------------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------------------


def test_a_record_from_another_model_is_refused(tmp_path, request_fixture):
    """The key covers model_id, so this only triggers on a hand-edited or merged cassette --
    exactly when a silent substitution would be least visible."""

    client, _inner, cassette = _client(tmp_path, CassetteMode.REPLAY)
    key = client.key_for(request_fixture)
    cassette.put(
        CassetteEntry(
            key=key,
            provider="openai_compat",
            model_id="some-other-model",
            recorded_at="2026-01-01T00:00:00+00:00",
            response=ModelResponse(content="from elsewhere"),
        )
    )
    with pytest.raises(CassetteMiss, match="may not stand in for a different model"):
        asyncio.run(client.complete(request_fixture))


def test_a_different_seed_is_a_different_record(tmp_path, request_fixture):
    """Repeated trials of a stochastic model must not collapse onto one recorded draw."""

    client, _inner, _ = _client(tmp_path, CassetteMode.REPLAY)
    first = client.key_for(request_fixture)
    second = client.key_for(request_fixture.model_copy(update={"seed": request_fixture.seed + 1}))
    assert first != second


def test_provider_state_is_absent_from_the_key(tmp_path, request_fixture):
    """It is derived from `messages`, which is already hashed. Including it would make an
    otherwise-identical request miss on the turn after a signature appears."""

    assert "provider_state" not in request_params(request_fixture)

    client, _inner, _ = _client(tmp_path, CassetteMode.REPLAY)
    without = client.key_for(request_fixture)
    with_state = client.key_for(
        request_fixture.model_copy(update={"provider_state": FrozenDict({"call_1": "SIG"})})
    )
    assert without == with_state


def test_the_key_is_stable_across_identical_requests(tmp_path, request_fixture):
    client, _inner, _ = _client(tmp_path, CassetteMode.REPLAY)
    assert client.key_for(request_fixture) == client.key_for(request_fixture)


# --------------------------------------------------------------------------------------
# Credentials never reach disk
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "leaked",
    [
        # A Google key is AIza + exactly 35 characters. The scan is shape-exact, so these
        # fixtures have to be too -- a loosely-shaped fake would pass and prove nothing.
        "AIzaSy" + "B" * 33,
        "sk-abcdefghijklmnopqrstuvwxyz012345",
        "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
    ],
)
def test_a_credential_in_a_response_is_refused_before_writing(tmp_path, leaked):
    """The export scan already guards the bundle. Scanning here too means a key never reaches
    disk in the first place, which is the only version of that guarantee worth having."""

    cassette = Cassette(tmp_path / "cassette")
    entry = CassetteEntry(
        key="blake2b128:" + "a" * 32,
        provider="openai_compat",
        model_id=MODEL,
        recorded_at="2026-01-01T00:00:00+00:00",
        response=ModelResponse(content=f"my key is {leaked}"),
    )
    with pytest.raises(ExportError, match="refusing to export"):
        cassette.put(entry)
    assert not list((tmp_path / "cassette").rglob("*.json.gz"))


def test_a_clean_response_writes_normally(tmp_path):
    cassette = Cassette(tmp_path / "cassette")
    entry = CassetteEntry(
        key="blake2b128:" + "b" * 32,
        provider="openai_compat",
        model_id=MODEL,
        recorded_at="2026-01-01T00:00:00+00:00",
        response=ModelResponse(content="nothing sensitive here"),
    )
    cassette.put(entry)
    assert cassette.get(entry.key) is not None


# --------------------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------------------


def test_records_are_sharded_and_gzipped(tmp_path, request_fixture):
    """Same layout as the response cache, so one directory of many thousands stays usable."""

    client, _inner, cassette = _client(tmp_path, CassetteMode.RECORD)
    asyncio.run(client.complete(request_fixture))

    files = list((tmp_path / "cassette").rglob("*.json.gz"))
    assert len(files) == 1
    assert files[0].parent.name == client.key_for(request_fixture).split(":", 1)[1][:2]
    with gzip.open(files[0], "rt", encoding="utf-8") as handle:
        assert "live answer" in handle.read()


def test_a_missing_cassette_directory_is_a_miss_not_a_crash(tmp_path, request_fixture):
    client, _inner, _ = _client(tmp_path / "does-not-exist", CassetteMode.REPLAY)
    with pytest.raises(CassetteMiss):
        asyncio.run(client.complete(request_fixture))


def test_entries_are_listed_in_a_stable_order(tmp_path):
    cassette = Cassette(tmp_path / "cassette")
    for index, char in enumerate("fedcba"):
        cassette.put(
            CassetteEntry(
                key="blake2b128:" + char * 32,
                provider="openai_compat",
                model_id=MODEL,
                recorded_at="2026-01-01T00:00:00+00:00",
                response=ModelResponse(content=str(index)),
            )
        )
    keys = [entry.key for entry in cassette.entries()]
    assert keys == sorted(keys)
