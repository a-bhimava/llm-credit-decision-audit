"""Bundle assembly: buffer, scan, budget, then write.

Every file is built in memory first and the whole bundle is validated before a single byte
reaches disk. That ordering is deliberate. A secret scan that runs *after* writing has already
lost -- the file exists, and on a repository that is published it may already be somewhere
else. The same applies to size budgets: a partially written 60 MB bundle is worse than a
refused export.

Writing is also what makes the determinism claim checkable. Files are emitted in sorted order
through :func:`~credit_audit.ids.portable_json`, and ``SHA256SUMS`` lists them sorted by path,
so ``export`` twice into two directories and ``diff -r`` is a real test rather than a hope.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

from credit_audit.ids import portable_json, sha256_bytes
from credit_audit.types import Frozen

MB = 1024 * 1024

SHA256SUMS = "integrity/SHA256SUMS"

DEFAULT_BUNDLE_ROOT = Path("web/public/runs")
"""Where published bundles live.

Declared here rather than in ``export`` because ``integrity`` needs it too, to name the bundle
in the commands it tells a reader to run, and importing the exporter from the integrity chain
would be a cycle.
"""


class ExportError(RuntimeError):
    """A bundle was refused. Every path that raises this is a rule enforced in code."""


class SizeBudget(Frozen):
    """Published size limits. A bundle that cannot be served is not evidence."""

    max_run_bytes: int = 15 * MB
    max_total_bytes: int = 40 * MB
    """Across every bundle under the publish root, not just this one.

    Enforced by :func:`check_total_bytes` after a bundle lands, because a single writer only
    ever sees its own run and the limit that actually matters is what the site ships.
    """

    max_file_bytes: int = 2 * MB
    max_files: int = 800


def check_total_bytes(out_root: Path, budget: SizeBudget) -> int:
    """Enforce the cross-run publish budget, returning the measured total.

    ``max_total_bytes`` was declared and never read while "≤40 MB total" was published as an
    enforced limit. A budget nothing checks is a wish. Measured over the whole publish root,
    since that is what a reader downloads and what the repository carries.
    """

    root = Path(out_root)
    if not root.exists():  # pragma: no cover - the caller just wrote a bundle into it
        return 0
    total = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    if total > budget.max_total_bytes:
        raise ExportError(
            f"published bundles under {root.as_posix()} total {total} bytes, over the "
            f"{budget.max_total_bytes}-byte budget. Drop a run, or raise the budget "
            "deliberately -- the limit is published as an enforced one."
        )
    return total


_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("OpenAI-style API key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}")),
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}")),
)


class BundleFile(Frozen):
    path: str
    sha256: str
    bytes: int


class BundleReport(Frozen):
    root: Path
    files: tuple[BundleFile, ...]
    total_bytes: int
    bundle_sha256: str

    @property
    def n_files(self) -> int:
        return len(self.files)


def scan_for_secrets(path: str, data: bytes, *, extra_needles: tuple[str, ...] = ()) -> None:
    """Refuse to write anything carrying a credential or a local absolute path.

    ``extra_needles`` is normally the exporting user's home directory. A published bundle that
    embeds ``/Users/someone/...`` leaks who built it and from where, and is the most likely
    accidental disclosure in a project that hashes file paths into its own provenance.
    """

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:  # pragma: no cover - every bundle file is UTF-8 JSON
        return
    for label, pattern in _SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            raise ExportError(
                f"refusing to export {path}: it contains what looks like a {label} "
                f"(matched {match.group(0)[:12]!r}...). Export aborted before writing."
            )
    for needle in extra_needles:
        if needle and needle in text:
            raise ExportError(
                f"refusing to export {path}: it embeds the local path {needle!r}. "
                "Paths in a published bundle must be repository-relative."
            )


def home_needles() -> tuple[str, ...]:
    """Local absolute paths that must never appear in a published file."""

    candidates = {os.path.expanduser("~"), os.environ.get("HOME", "")}
    return tuple(sorted(needle for needle in candidates if needle and needle != "/"))


class BundleWriter:
    """Collects bundle files in memory, validates the whole set, then writes it."""

    def __init__(
        self,
        root: Path,
        *,
        budget: SizeBudget | None = None,
        secret_needles: tuple[str, ...] | None = None,
    ) -> None:
        self._root = Path(root)
        self._budget = budget or SizeBudget()
        self._needles = home_needles() if secret_needles is None else secret_needles
        self._files: dict[str, bytes] = {}

    @property
    def root(self) -> Path:
        return self._root

    @property
    def buffered(self) -> dict[str, bytes]:
        """Everything staged so far, for whole-bundle checks that run before writing.

        A copy: a caller inspecting the bundle must not be able to edit it on the way past.
        """

        return dict(self._files)

    def add_json(self, relpath: str, payload: Any) -> None:
        self.add_bytes(relpath, portable_json(payload) + b"\n")

    def add_text(self, relpath: str, text: str) -> None:
        self.add_bytes(relpath, text.encode("utf-8"))

    def add_bytes(self, relpath: str, data: bytes) -> None:
        if relpath in self._files:
            raise ExportError(f"{relpath} was added to the bundle twice")
        if relpath.startswith("/") or ".." in Path(relpath).parts:
            raise ExportError(f"bundle paths must be relative and contained: {relpath!r}")
        self._files[relpath] = data

    def listing(self) -> tuple[BundleFile, ...]:
        """Hashes of everything buffered so far, sorted by path."""

        return tuple(
            BundleFile(path=path, sha256=sha256_bytes(data), bytes=len(data))
            for path, data in sorted(self._files.items())
        )

    @staticmethod
    def sums_text(listing: tuple[BundleFile, ...]) -> str:
        return "".join(
            f"{entry.sha256.removeprefix('sha256:')}  {entry.path}\n" for entry in listing
        )

    def digest(self) -> str:
        """Hash of the current file set, for the two files that must report it.

        ``manifest.json`` and ``integrity/chain.json`` both carry ``bundle_sha256``, and a file
        cannot contain its own hash. This digest therefore covers every *content* file and is
        computed before those two are added. ``SHA256SUMS`` still lists all of them, so nothing
        escapes verification -- the two self-describing files are checked by the sums file, and
        everything else is checked by both.
        """

        return sha256_bytes(self.sums_text(self.listing()).encode("utf-8"))

    def _enforce(self) -> None:
        budget = self._budget
        if len(self._files) > budget.max_files:
            raise ExportError(
                f"bundle has {len(self._files)} files, over the {budget.max_files} limit; "
                "reduce exported pair detail rather than raising the budget"
            )
        for path, data in sorted(self._files.items()):
            if len(data) > budget.max_file_bytes:
                raise ExportError(
                    f"{path} is {len(data) / MB:.1f} MB, over the "
                    f"{budget.max_file_bytes / MB:.0f} MB per-file limit"
                )
            scan_for_secrets(path, data, extra_needles=self._needles)
        total = sum(len(data) for data in self._files.values())
        if total > budget.max_run_bytes:
            raise ExportError(
                f"bundle is {total / MB:.1f} MB, over the {budget.max_run_bytes / MB:.0f} MB "
                "per-run limit"
            )

    def finalize(self) -> BundleReport:
        """Validate everything, then write the bundle and its integrity manifest.

        The destination directory is replaced wholesale. A stale file left behind from a
        previous export would still be served, and would still hash, and nothing downstream
        would notice.
        """

        self._enforce()

        listing = self.listing()
        sums_bytes = self.sums_text(listing).encode("utf-8")
        bundle_sha = sha256_bytes(sums_bytes)

        if self._root.exists():
            shutil.rmtree(self._root)
        for path, data in sorted(self._files.items()):
            destination = self._root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        sums_path = self._root / SHA256SUMS
        sums_path.parent.mkdir(parents=True, exist_ok=True)
        sums_path.write_bytes(sums_bytes)

        return BundleReport(
            root=self._root,
            files=listing,
            total_bytes=sum(entry.bytes for entry in listing) + len(sums_bytes),
            bundle_sha256=bundle_sha,
        )


__all__ = [
    "MB",
    "SHA256SUMS",
    "BundleFile",
    "BundleReport",
    "BundleWriter",
    "ExportError",
    "SizeBudget",
    "home_needles",
    "scan_for_secrets",
]
