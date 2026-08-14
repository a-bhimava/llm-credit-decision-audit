"""`verify` re-derives the bundle from raw evidence, and notices when it cannot.

Re-exporting and diffing proves the exporter is deterministic. These tests prove it is
*correct*: that the published numbers are the numbers the evidence supports, and that
tampering with either side is detected rather than absorbed.
"""

from __future__ import annotations

import json

import pytest

from credit_audit.report.verify import verify_bundle

from .conftest import BOOTSTRAP_B, FIXED_GIT


def test_a_freshly_exported_bundle_verifies(smoke_run, smoke_bundle):
    report = verify_bundle(
        smoke_run.run_dir, smoke_bundle.root, strict=True, bootstrap_B=BOOTSTRAP_B
    )
    assert report.ok, report.format()
    claims = [finding.claim for finding in report.findings]
    assert any("matches its hash" in claim for claim in claims)
    assert any("re-derive from" in claim for claim in claims)
    assert any("summary re-derives" in claim for claim in claims)
    assert any("headline resolves" in claim for claim in claims)


def test_the_report_formats_a_readable_verdict(smoke_run, smoke_bundle):
    report = verify_bundle(
        smoke_run.run_dir, smoke_bundle.root, strict=True, bootstrap_B=BOOTSTRAP_B
    )
    text = report.format()
    assert text.startswith(f"verify {smoke_run.run_id}")
    assert text.rstrip().endswith("PASS")


def test_tampering_with_a_published_file_is_caught(smoke_run, tmp_path):
    """The hash chain, doing the one job it exists for."""

    from credit_audit.report.export import export_run

    exported = export_run(
        smoke_run.run_dir, out_root=tmp_path, git=FIXED_GIT, bootstrap_B=BOOTSTRAP_B
    )
    target = exported.root / "summary.json"
    payload = json.loads(target.read_text())
    payload["headline"][0]["value"] = 0.99
    target.write_text(json.dumps(payload))

    report = verify_bundle(smoke_run.run_dir, exported.root, strict=True, bootstrap_B=BOOTSTRAP_B)
    assert not report.ok
    assert any("matches its hash" in finding.claim for finding in report.failures)


def test_an_edited_statistic_is_caught_even_if_the_hashes_are_rebuilt(smoke_run, tmp_path):
    """Re-hashing a doctored file defeats the sums check, not the re-derivation.

    This is the attack the sums file alone cannot catch, and the reason `verify` recomputes
    the statistics instead of only checking hashes.
    """

    from credit_audit.ids import sha256_bytes
    from credit_audit.report.bundle import SHA256SUMS
    from credit_audit.report.export import export_run

    exported = export_run(
        smoke_run.run_dir, out_root=tmp_path, git=FIXED_GIT, bootstrap_B=BOOTSTRAP_B
    )
    target = exported.root / "stats" / "estimates.json"
    payload = json.loads(target.read_text())
    payload["estimates"][0]["point"] = 0.42
    doctored = json.dumps(payload).encode("utf-8")
    target.write_bytes(doctored)

    sums_path = exported.root / SHA256SUMS
    rebuilt = []
    for line in sums_path.read_text().splitlines():
        _digest, _, relpath = line.partition("  ")
        data = (exported.root / relpath).read_bytes()
        rebuilt.append(f"{sha256_bytes(data).removeprefix('sha256:')}  {relpath}")
    sums_path.write_text("\n".join(rebuilt) + "\n")

    report = verify_bundle(smoke_run.run_dir, exported.root, strict=True, bootstrap_B=BOOTSTRAP_B)
    assert not report.ok
    failures = [finding for finding in report.failures if "re-derive" in finding.claim]
    assert failures
    assert "point" in failures[0].detail


def test_a_changed_raw_artifact_is_caught_and_stops_the_rest(smoke_run, smoke_bundle):
    """If the evidence moved under the bundle, comparing against it proves nothing."""

    from credit_audit.run.execute import RESULTS_FILE

    path = smoke_run.run_dir / RESULTS_FILE
    original = path.read_bytes()
    try:
        path.write_bytes(original + b'{"tampered":true}\n')
        report = verify_bundle(
            smoke_run.run_dir, smoke_bundle.root, strict=True, bootstrap_B=BOOTSTRAP_B
        )
        assert not report.ok
        assert any("raw run artifacts" in finding.claim for finding in report.failures)
        # Nothing downstream is reported once the evidence itself is in question.
        assert not any("re-derive" in finding.claim for finding in report.findings)
    finally:
        path.write_bytes(original)


def test_strict_re_derives_every_published_file(smoke_run, smoke_bundle):
    """Lenient checks the hashes and the statistics; strict rebuilds the bundle."""

    lenient = verify_bundle(
        smoke_run.run_dir, smoke_bundle.root, strict=False, bootstrap_B=BOOTSTRAP_B
    )
    strict = verify_bundle(
        smoke_run.run_dir, smoke_bundle.root, strict=True, bootstrap_B=BOOTSTRAP_B
    )
    assert lenient.ok and strict.ok
    assert len(strict.findings) > len(lenient.findings)
    assert any("re-derive from the raw artifacts" in f.claim for f in strict.findings)
    assert any("nothing beyond what the exporter produces" in f.claim for f in strict.findings)


@pytest.mark.parametrize(
    ("relpath", "mutate"),
    [
        ("report.md", lambda data: data + b"\n\nThe model failed 99% of tests.\n"),
        ("policy.json", lambda data: data.replace(b"{", b'{"injected": 1,', 1)),
        ("checks/index.json", lambda data: data.replace(b"{", b'{"injected": 1,', 1)),
    ],
)
def test_doctoring_a_file_is_caught_even_with_rebuilt_hashes(
    smoke_run, tmp_path, policy, relpath, mutate
):
    """The gap that mattered: these three passed --strict once their hashes were rebuilt.

    Only estimates, the summary, and the check rows were ever re-derived, so a reader could be
    handed a report.md carrying a claim about a model that no run produced -- and the pair
    files, the evidence a skeptic actually opens, were unchecked. Parametrized over one file
    from each previously-unverified class.
    """

    from credit_audit.report.export import export_run

    exported = export_run(
        smoke_run.run_dir,
        out_root=tmp_path,
        policy=policy,
        git=FIXED_GIT,
        bootstrap_B=BOOTSTRAP_B,
    )
    target = exported.root / relpath
    target.write_bytes(mutate(target.read_bytes()))
    _rebuild_sums(exported.root)

    report = verify_bundle(smoke_run.run_dir, exported.root, strict=True, bootstrap_B=BOOTSTRAP_B)
    assert not report.ok
    assert any(relpath in finding.detail for finding in report.failures), report.format()


def test_doctoring_a_pair_file_is_caught(smoke_run, tmp_path, policy):
    """The drill-down evidence, which is the whole point of the pair viewer."""

    import json as _json

    from credit_audit.report.export import export_run

    exported = export_run(
        smoke_run.run_dir,
        out_root=tmp_path,
        policy=policy,
        git=FIXED_GIT,
        bootstrap_B=BOOTSTRAP_B,
    )
    target = sorted((exported.root / "pairs").glob("*.json"))[0]
    payload = _json.loads(target.read_text())
    payload["hypothesis"]["plain_english"] = "Something the harness never concluded."
    target.write_bytes(_json.dumps(payload).encode("utf-8"))
    _rebuild_sums(exported.root)

    report = verify_bundle(smoke_run.run_dir, exported.root, strict=True, bootstrap_B=BOOTSTRAP_B)
    assert not report.ok
    assert any("pairs/" in finding.detail for finding in report.failures), report.format()


def test_an_extra_file_smuggled_into_a_bundle_is_caught(smoke_run, tmp_path, policy):
    """SHA256SUMS only ever covered what it listed, so an added file went unnoticed."""

    from credit_audit.report.export import export_run

    exported = export_run(
        smoke_run.run_dir,
        out_root=tmp_path,
        policy=policy,
        git=FIXED_GIT,
        bootstrap_B=BOOTSTRAP_B,
    )
    (exported.root / "stats" / "extra.json").write_text('{"smuggled": true}')
    _rebuild_sums(exported.root)

    report = verify_bundle(smoke_run.run_dir, exported.root, strict=True, bootstrap_B=BOOTSTRAP_B)
    assert not report.ok
    assert any("stats/extra.json" in finding.detail for finding in report.failures)


def _rebuild_sums(root):
    """Rewrite SHA256SUMS so only re-derivation can catch the edit, not the hash check."""

    from credit_audit.ids import sha256_bytes
    from credit_audit.report.bundle import SHA256SUMS

    sums_path = root / SHA256SUMS
    rebuilt = []
    for line in sums_path.read_text().splitlines():
        if not line.strip():
            continue
        _digest, _, relpath = line.partition("  ")
        data = (root / relpath).read_bytes()
        rebuilt.append(f"{sha256_bytes(data).removeprefix('sha256:')}  {relpath}")
    sums_path.write_text("\n".join(rebuilt) + "\n")
