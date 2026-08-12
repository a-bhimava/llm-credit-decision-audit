"""`verify` re-derives the bundle from raw evidence, and notices when it cannot.

Re-exporting and diffing proves the exporter is deterministic. These tests prove it is
*correct*: that the published numbers are the numbers the evidence supports, and that
tampering with either side is detected rather than absorbed.
"""

from __future__ import annotations

import json

from credit_audit.report.verify import verify_bundle

from .conftest import BOOTSTRAP_B


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

    exported = export_run(smoke_run.run_dir, out_root=tmp_path, git=None, bootstrap_B=BOOTSTRAP_B)
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

    exported = export_run(smoke_run.run_dir, out_root=tmp_path, git=None, bootstrap_B=BOOTSTRAP_B)
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


def test_strict_adds_the_check_row_tables(smoke_run, smoke_bundle):
    lenient = verify_bundle(
        smoke_run.run_dir, smoke_bundle.root, strict=False, bootstrap_B=BOOTSTRAP_B
    )
    strict = verify_bundle(
        smoke_run.run_dir, smoke_bundle.root, strict=True, bootstrap_B=BOOTSTRAP_B
    )
    assert lenient.ok and strict.ok
    assert len(strict.findings) == len(lenient.findings) + 1
    assert any("check-row tables" in finding.claim for finding in strict.findings)
