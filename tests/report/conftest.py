"""One scripted run, exported once, shared by the whole export test module.

The run is real -- `smoke` through the actual pipeline -- because an exporter tested against
hand-built records proves nothing about whether it can consume what a run actually writes.
"""

from __future__ import annotations

import asyncio

import pytest

from credit_audit.model.scripted import FaithfulAgent, NonMonotoneAgent
from credit_audit.report.export import export_run
from credit_audit.run.execute import execute_run
from credit_audit.run.gitmeta import GitMetadata
from credit_audit.suites.loader import load_suite

SEED = 1729
BOOTSTRAP_B = 200

FIXED_GIT = GitMetadata(
    commit="b" * 40,
    short="bbbbbbb",
    dirty=False,
    remote="https://example.invalid/repo.git",
    tag=None,
)


def execute_smoke(tmp_path, policy, client=None):
    return asyncio.run(
        execute_run(
            suite=load_suite("smoke"),
            client=client or FaithfulAgent(),
            policy=policy,
            seed=SEED,
            runs_dir=tmp_path / "runs",
            git=FIXED_GIT,
        )
    )


@pytest.fixture(scope="module")
def smoke_run(tmp_path_factory, policy):
    return execute_smoke(tmp_path_factory.mktemp("faithful"), policy)


@pytest.fixture(scope="module")
def smoke_bundle(smoke_run, tmp_path_factory, policy):
    out = tmp_path_factory.mktemp("bundle")
    outcome = export_run(
        smoke_run.run_dir,
        out_root=out,
        policy=policy,
        git=FIXED_GIT,
        bootstrap_B=BOOTSTRAP_B,
    )
    return outcome


@pytest.fixture(scope="module")
def defect_run(tmp_path_factory, policy):
    return execute_smoke(tmp_path_factory.mktemp("defect"), policy, client=NonMonotoneAgent())
