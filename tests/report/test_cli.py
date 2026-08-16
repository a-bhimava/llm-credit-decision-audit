"""The CLI: the three verbs, and the end-to-end gate the roadmap names as Phase 8's exit."""

from __future__ import annotations

import argparse
import filecmp
from pathlib import Path

import pytest

from credit_audit.cli import _apply_spend_authorization, build_client, main
from credit_audit.suites.loader import load_suite


def _dircmp_equal(left: Path, right: Path) -> bool:
    """`diff -r`, as a predicate."""

    comparison = filecmp.dircmp(left, right)
    if comparison.left_only or comparison.right_only or comparison.diff_files:
        return False
    return all(_dircmp_equal(left / name, right / name) for name in comparison.common_dirs)


def test_scripted_is_the_faithful_control():
    client, kind, provider = build_client("scripted")
    assert client.model_id == "scripted:faithful"
    assert kind == "scripted"
    assert provider == "scripted"


def test_a_specific_defect_agent_can_be_selected():
    client, _, _ = build_client("scripted:non_monotone")
    assert client.model_id == "scripted:non_monotone"


def test_a_bare_model_id_is_rejected_with_the_shapes_that_work():
    """Providers exist now, but they are addressed by scheme so `kind` is never guessed."""

    with pytest.raises(SystemExit, match="gemini:<id>"):
        build_client("gemini-2.5-flash-lite")


def test_a_provider_model_is_kind_model_not_scripted(monkeypatch):
    """The field that drives the provenance banner and disables the scripted-claim lint."""

    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    client, kind, provider = build_client("gemini:gemini-2.5-flash-lite")
    assert kind == "model"
    assert provider == "gemini_openai_compat"
    assert client.model_id == "gemini-2.5-flash-lite"


def test_a_provider_without_a_key_says_where_to_put_it(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="Export it in your shell"):
        build_client("gemini:gemini-2.5-flash-lite")


@pytest.mark.parametrize(
    ("max_usd", "max_wall_seconds", "expected_usd", "expected_tokens", "expected_wall"),
    [
        (None, None, 0.0, 0, 1800.0),
        (None, 7200.0, 0.0, 0, 7200.0),
        (5.0, None, 5.0, None, 1800.0),
        (5.0, 7200.0, 5.0, None, 7200.0),
    ],
)
def test_spend_and_wall_authorizations_merge_in_all_flag_combinations(
    max_usd, max_wall_seconds, expected_usd, expected_tokens, expected_wall
):
    suite = _apply_spend_authorization(
        load_suite("core"),
        argparse.Namespace(max_usd=max_usd, max_wall_seconds=max_wall_seconds),
    )
    assert suite.caps.max_usd == expected_usd
    assert suite.caps.max_tokens == expected_tokens
    assert suite.caps.max_wall_seconds == expected_wall


def test_an_unknown_scripted_agent_lists_the_real_ones():
    with pytest.raises(SystemExit, match="Available:"):
        build_client("scripted:nonexistent")


def test_dry_run_prints_the_plan_and_executes_nothing(tmp_path, capsys):
    runs = tmp_path / "runs"
    code = main(
        ["run", "--suite", "smoke", "--model", "scripted", "--runs-dir", str(runs), "--dry-run"]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "total episodes" in out
    assert "nothing was executed" in out
    assert not runs.exists()


def test_run_export_verify_round_trip(tmp_path, capsys):
    """The Phase 8 exit criterion, end to end through the real entry point.

    run -> export -> export again to a second directory -> byte-identical -> verify --strict.
    """

    runs = tmp_path / "runs"
    bundle_a = tmp_path / "a"
    bundle_b = tmp_path / "b"

    assert main(["run", "--suite", "smoke", "--seed", "1729", "--runs-dir", str(runs)]) == 0
    run_id = next(path.name for path in runs.iterdir() if path.name.startswith("run_"))
    capsys.readouterr()

    assert main(["export", "--run", run_id, "--runs-dir", str(runs), "--out", str(bundle_a)]) == 0
    first = capsys.readouterr().out
    assert main(["export", "--run", run_id, "--runs-dir", str(runs), "--out", str(bundle_b)]) == 0
    second = capsys.readouterr().out

    assert "bundle sha256" in first
    assert first.replace(str(bundle_a), "") == second.replace(str(bundle_b), "")
    assert _dircmp_equal(bundle_a / run_id, bundle_b / run_id), "re-export must be byte-identical"

    assert (
        main(
            [
                "verify",
                "--run",
                run_id,
                "--runs-dir",
                str(runs),
                "--out",
                str(bundle_a),
                "--strict",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.rstrip().endswith("PASS")


def test_verify_exits_nonzero_when_the_bundle_disagrees(tmp_path, capsys):
    runs = tmp_path / "runs"
    bundle = tmp_path / "bundle"
    main(["run", "--suite", "smoke", "--runs-dir", str(runs)])
    run_id = next(path.name for path in runs.iterdir() if path.name.startswith("run_"))
    main(["export", "--run", run_id, "--runs-dir", str(runs), "--out", str(bundle)])
    capsys.readouterr()

    target = bundle / run_id / "summary.json"
    target.write_text(target.read_text().replace('"kind":"scripted"', '"kind":"model"'))

    code = main(["verify", "--run", run_id, "--runs-dir", str(runs), "--out", str(bundle)])
    assert code == 1
    assert "FAILED" in capsys.readouterr().out


def test_export_before_run_says_so(tmp_path):
    with pytest.raises(SystemExit, match="credit-audit run"):
        main(["export", "--run", "run_missing", "--runs-dir", str(tmp_path)])


def test_verify_before_export_says_so(tmp_path, capsys):
    runs = tmp_path / "runs"
    main(["run", "--suite", "smoke", "--runs-dir", str(runs)])
    run_id = next(path.name for path in runs.iterdir() if path.name.startswith("run_"))
    capsys.readouterr()
    with pytest.raises(SystemExit, match="credit-audit export"):
        main(["verify", "--run", run_id, "--runs-dir", str(runs), "--out", str(tmp_path / "no")])
