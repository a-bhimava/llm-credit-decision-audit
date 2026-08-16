"""Archive verified partial attempts without making them published evidence.

An aborted provider run is useful accounting and provenance, but it must not enter
``web/public`` or the run index.  This module copies only the manifest and the manifest-addressed
raw artifacts into the ignored ``runs/attempts`` tree, checks every digest before and after the
copy, and records the explicit reason the attempt stopped.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from credit_audit.ids import sha256_file
from credit_audit.io.jsonl import write_json
from credit_audit.run.execute import MANIFEST_FILE, load_run_manifest

ATTEMPT_SCHEMA = "credit-audit/attempt@1"
ATTEMPT_RECORD_FILE = "attempt.json"


def archive_aborted_attempt(
    run_dir: Path,
    *,
    attempts_dir: Path,
    abort_reason: str,
) -> Path:
    """Copy one verified partial run into a content-addressed local attempt archive.

    Legacy manifests did not carry a terminal status.  They are eligible only when their
    counts prove the run is partial and an operator supplies the reason explicitly.  Newer
    manifests already carry that status, but the supplied reason must still agree with it so
    the archive is a durable human-readable record rather than a guessed diagnosis.
    """

    run_dir = Path(run_dir)
    attempts_dir = Path(attempts_dir)
    if not abort_reason.strip():
        raise ValueError("abort_reason must not be blank")

    manifest, deterministic = load_run_manifest(run_dir)
    partial = manifest.counts.executed < manifest.counts.planned
    if manifest.terminal_status != "aborted" and not partial:
        raise ValueError(
            "only an aborted or demonstrably partial run may be archived as an attempt"
        )
    if manifest.terminal_status == "aborted" and manifest.abort_reason != abort_reason:
        raise ValueError("abort_reason must exactly match the persisted manifest")

    source_manifest = run_dir / MANIFEST_FILE
    if not source_manifest.is_file():
        raise ValueError(f"missing source manifest: {source_manifest}")
    artifacts = _verify_source_artifacts(run_dir, dict(manifest.artifacts))
    manifest_sha256 = sha256_file(source_manifest)
    digest = manifest_sha256.removeprefix("sha256:")
    destination = attempts_dir / manifest.run_id / digest
    payload = _attempt_payload(
        manifest=manifest,
        deterministic=deterministic,
        manifest_sha256=manifest_sha256,
        abort_reason=abort_reason,
        artifacts=artifacts,
    )

    if destination.exists():
        _verify_existing_archive(destination, payload)
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".attempt-", dir=destination.parent))
    try:
        shutil.copy2(source_manifest, temporary / MANIFEST_FILE)
        for name in artifacts:
            source = run_dir / name
            target = temporary / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        _verify_source_artifacts(temporary, artifacts)
        write_json(temporary / ATTEMPT_RECORD_FILE, payload)
        os.replace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return destination


def _verify_source_artifacts(run_dir: Path, artifacts: dict[str, Any]) -> dict[str, str]:
    if not artifacts:
        raise ValueError("source manifest has no artifact digests to verify")
    verified: dict[str, str] = {}
    for name, expected in sorted(artifacts.items()):
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe artifact path in manifest: {name!r}")
        source = run_dir / relative
        if not source.is_file():
            raise ValueError(f"manifest artifact is missing: {source}")
        actual = sha256_file(source)
        if actual != expected:
            raise ValueError(
                f"manifest artifact digest mismatch for {name}: {actual} != {expected}"
            )
        verified[name] = actual
    return verified


def _attempt_payload(
    *,
    manifest,
    deterministic: bool,
    manifest_sha256: str,
    abort_reason: str,
    artifacts: dict[str, str],
) -> dict[str, Any]:
    return {
        "schema": ATTEMPT_SCHEMA,
        "source_run_id": manifest.run_id,
        "source_manifest_sha256": manifest_sha256,
        "source_terminal_status": manifest.terminal_status,
        "archived_status": "aborted",
        "abort_reason": abort_reason,
        "deterministic": deterministic,
        "counts": manifest.counts.model_dump(mode="json"),
        "cost": manifest.cost.model_dump(mode="json"),
        "artifacts": artifacts,
    }


def _verify_existing_archive(destination: Path, expected_payload: dict[str, Any]) -> None:
    import json

    record_path = destination / ATTEMPT_RECORD_FILE
    if not record_path.is_file():
        raise ValueError(f"archive destination exists without {ATTEMPT_RECORD_FILE}: {destination}")
    actual_payload = json.loads(record_path.read_text(encoding="utf-8"))
    if actual_payload != expected_payload:
        raise ValueError(f"archive destination conflicts with this attempt: {destination}")
    _verify_source_artifacts(destination, dict(expected_payload["artifacts"]))
    source_manifest = destination / MANIFEST_FILE
    if (
        not source_manifest.is_file()
        or sha256_file(source_manifest) != expected_payload["source_manifest_sha256"]
    ):
        raise ValueError(f"archived manifest digest mismatch: {destination}")


__all__ = ["ATTEMPT_RECORD_FILE", "ATTEMPT_SCHEMA", "archive_aborted_attempt"]
