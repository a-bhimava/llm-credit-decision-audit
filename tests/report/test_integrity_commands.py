"""The commands a skeptic is told to run have to run.

`integrity/chain.json` publishes literal shell commands beside the claims they check, on the
argument that a claim nobody can check in one paste is a claim on trust. Both bundle-facing
commands pointed at `runs/<run_id>` -- the gitignored raw-artifact directory -- so pasting the
first one produced `shasum: integrity/SHA256SUMS: No such file or directory`.

Nothing executed them, which is why nobody noticed.
"""

from __future__ import annotations

import json
import shutil
import subprocess

from credit_audit.report.bundle import DEFAULT_BUNDLE_ROOT
from credit_audit.report.export import export_run

from .conftest import BOOTSTRAP_B, FIXED_GIT


def _chain(bundle_root):
    return json.loads((bundle_root / "integrity" / "chain.json").read_text())


def test_the_hash_command_runs_against_the_published_bundle(smoke_run, tmp_path, policy):
    """The one command every reader will actually try."""

    exported = export_run(
        smoke_run.run_dir,
        out_root=tmp_path,
        policy=policy,
        git=FIXED_GIT,
        bootstrap_B=BOOTSTRAP_B,
    )
    published = _chain(exported.root)["verify"][0]["cmd"]

    # The command names the canonical publish root, since that is where a reader's copy lives.
    # Rehost the bundle there under tmp_path and run the command exactly as published.
    staged = tmp_path / "repo" / DEFAULT_BUNDLE_ROOT / exported.run_id
    staged.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(exported.root, staged)

    completed = subprocess.run(
        published,
        shell=True,
        cwd=tmp_path / "repo",
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, f"{published!r} failed:\n{completed.stderr}"
    assert "FAILED" not in completed.stdout


def test_every_published_command_names_a_path_that_exists(smoke_run, tmp_path, policy):
    """A command pointing at the raw-artifact directory is the bug this guards."""

    exported = export_run(
        smoke_run.run_dir,
        out_root=tmp_path,
        policy=policy,
        git=FIXED_GIT,
        bootstrap_B=BOOTSTRAP_B,
    )
    run_id = exported.run_id
    bundle_dir = f"{DEFAULT_BUNDLE_ROOT.as_posix()}/{run_id}"

    for entry in _chain(exported.root)["verify"]:
        cmd = entry["cmd"]
        assert entry["claim"], "a command without a claim is not evidence of anything"
        # No command may reference the gitignored raw-artifact directory as though a reader
        # had it. `runs/<id>` is only legitimate inside a `credit-audit` invocation's --run.
        assert f"cd runs/{run_id}" not in cmd
        assert f"diff -r /tmp/recheck/runs/{run_id}" not in cmd
        if "shasum" in cmd or "diff -r" in cmd:
            assert bundle_dir in cmd, f"{cmd!r} does not name the published bundle"
