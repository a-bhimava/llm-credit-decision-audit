"""Re-derive a published bundle from raw evidence and report every disagreement.

``export`` is trusted by nobody, including itself. ``verify`` reads the run's raw JSONL back,
recomputes the statistics and the summary from scratch, and compares them to what was
published -- then checks that every published byte matches the hash beside it.

The distinction from ``diff -r`` matters. Re-exporting and diffing proves the exporter is
deterministic. Re-deriving proves the exporter is *correct*: that the numbers on the page are
the numbers the evidence supports, not the numbers a bug produced consistently.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from credit_audit.ids import sha256_bytes, sha256_file
from credit_audit.report.bundle import SHA256SUMS
from credit_audit.report.checks import build_check_rows, group_by_check, rows_file_for
from credit_audit.report.export import check_headline_support, lint_scripted_headlines
from credit_audit.report.summary import build_summary
from credit_audit.run.execute import (
    load_run_manifest,
    load_run_results,
    load_run_trajectories,
)
from credit_audit.stats.estimates import build_estimates
from credit_audit.stats.families import Preregistration, load_preregistration
from credit_audit.types import Frozen


class VerifyFinding(Frozen):
    claim: str
    ok: bool
    detail: str = ""


class VerifyReport(Frozen):
    run_id: str
    findings: tuple[VerifyFinding, ...]

    @property
    def ok(self) -> bool:
        return all(finding.ok for finding in self.findings)

    @property
    def failures(self) -> tuple[VerifyFinding, ...]:
        return tuple(finding for finding in self.findings if not finding.ok)

    def format(self) -> str:
        lines = [f"verify {self.run_id}"]
        for finding in self.findings:
            mark = "ok  " if finding.ok else "FAIL"
            lines.append(f"  [{mark}] {finding.claim}")
            if finding.detail:
                lines.append(f"         {finding.detail}")
        lines.append("")
        lines.append("PASS" if self.ok else f"FAILED ({len(self.failures)} findings)")
        return "\n".join(lines)


def _first_difference(expected: Any, actual: Any, path: str = "$") -> str | None:
    """The first place two documents disagree, as a path a human can act on."""

    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual)):
            if key not in expected:
                return f"{path}.{key}: unexpected key in published bundle"
            if key not in actual:
                return f"{path}.{key}: missing from published bundle"
            found = _first_difference(expected[key], actual[key], f"{path}.{key}")
            if found:
                return found
        return None
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return f"{path}: re-derived {len(expected)} entries, bundle has {len(actual)}"
        for index, (left, right) in enumerate(zip(expected, actual, strict=True)):
            found = _first_difference(left, right, f"{path}[{index}]")
            if found:
                return found
        return None
    if expected != actual:
        return f"{path}: re-derived {expected!r}, bundle has {actual!r}"
    return None


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_bundle(
    run_dir: Path,
    bundle_root: Path,
    *,
    prereg: Preregistration | None = None,
    strict: bool = True,
    bootstrap_B: int | None = None,
) -> VerifyReport:
    """Check a published bundle against the raw artifacts it claims to summarize."""

    run_dir = Path(run_dir)
    bundle_root = Path(bundle_root)
    prereg = prereg or load_preregistration()

    manifest, _deterministic = load_run_manifest(run_dir)
    findings: list[VerifyFinding] = []

    # 1. The published bytes are the bytes that were hashed.
    sums_path = bundle_root / SHA256SUMS
    mismatches: list[str] = []
    listed = 0
    if not sums_path.exists():
        findings.append(
            VerifyFinding(claim="integrity/SHA256SUMS is present", ok=False, detail="missing")
        )
    else:
        for line in sums_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            digest, _, relpath = line.partition("  ")
            listed += 1
            target = bundle_root / relpath
            if not target.exists():
                mismatches.append(f"{relpath}: listed but absent")
                continue
            if sha256_bytes(target.read_bytes()) != f"sha256:{digest}":
                mismatches.append(f"{relpath}: content does not match its published hash")
        findings.append(
            VerifyFinding(
                claim=f"every one of {listed} published files matches its hash",
                ok=not mismatches,
                detail="; ".join(mismatches[:3]),
            )
        )

    # 2. The bundle describes the artifacts it was built from.
    artifact_problems = []
    for name, expected in sorted(manifest.artifacts.items()):
        path = run_dir / name
        if not path.exists():
            artifact_problems.append(f"{name}: raw artifact missing")
            continue
        if sha256_file(path) != str(expected):
            artifact_problems.append(f"{name}: raw artifact has changed since the run")
    findings.append(
        VerifyFinding(
            claim="raw run artifacts match the hashes recorded at run time",
            ok=not artifact_problems,
            detail="; ".join(artifact_problems),
        )
    )
    if artifact_problems:
        # Every remaining check re-derives from those artifacts; continuing would compare
        # against evidence already known to have changed.
        return VerifyReport(run_id=manifest.run_id, findings=tuple(findings))

    results = load_run_results(run_dir)
    trajectories = load_run_trajectories(run_dir)

    # 3. Every statistic re-derives from the raw results.
    estimates_path = bundle_root / "stats" / "estimates.json"
    if estimates_path.exists():
        rederived = build_estimates(results, prereg=prereg, B=bootstrap_B)
        published = _load(estimates_path)
        difference = _first_difference(rederived, published)
        findings.append(
            VerifyFinding(
                claim=(
                    f"all {len(rederived.get('estimates', ()))} estimates re-derive from "
                    f"{len(results)} raw results"
                ),
                ok=difference is None,
                detail=difference or "",
            )
        )
    else:
        rederived = {}
        findings.append(
            VerifyFinding(claim="stats/estimates.json is present", ok=False, detail="missing")
        )

    # 4. The summary is a function of the results, not an editorial layer.
    summary_path = bundle_root / "summary.json"
    if summary_path.exists() and rederived:
        rebuilt = build_summary(
            run_id=manifest.run_id,
            kind=manifest.kind,
            results=results,
            trajectories=trajectories,
            estimates_doc=rederived,
            prereg=prereg,
        )
        published_summary = _load(summary_path)
        difference = _first_difference(rebuilt, published_summary)
        findings.append(
            VerifyFinding(
                claim="the summary re-derives from the raw results",
                ok=difference is None,
                detail=difference or "",
            )
        )
        try:
            check_headline_support(published_summary, _load(estimates_path))
            lint_scripted_headlines(published_summary)
            findings.append(
                VerifyFinding(
                    claim="every headline resolves to an estimate and passes the claim lint",
                    ok=True,
                )
            )
        except Exception as error:  # noqa: BLE001 - reported, not swallowed
            findings.append(
                VerifyFinding(
                    claim="every headline resolves to an estimate and passes the claim lint",
                    ok=False,
                    detail=str(error),
                )
            )

    # 5. Every exported check-rows table re-derives from the raw results.
    if strict:
        grouped = group_by_check(results)
        row_problems: list[str] = []
        for check, bucket in grouped.items():
            path = bundle_root / rows_file_for(check)
            if not path.exists():
                row_problems.append(f"{check}: rows file missing")
                continue
            difference = _first_difference(
                build_check_rows(check, bucket, run_id=manifest.run_id), _load(path)
            )
            if difference:
                row_problems.append(f"{check}: {difference}")
        findings.append(
            VerifyFinding(
                claim=f"all {len(grouped)} check-row tables re-derive from the raw results",
                ok=not row_problems,
                detail="; ".join(row_problems[:3]),
            )
        )

    return VerifyReport(run_id=manifest.run_id, findings=tuple(findings))


__all__ = ["VerifyFinding", "VerifyReport", "verify_bundle"]
