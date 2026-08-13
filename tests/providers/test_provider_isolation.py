"""A real adapter must see what a real model sees, and nothing else.

`ModelRequest` carries `env_state` because scripted agents and cassettes need it. A provider
adapter that reached into it could consult ground truth — the oracle's decision, the
applicant's true facts, the policy object — and produce a "real model run" that was quietly
cheating. Nothing downstream would notice: the trajectory would look ordinary, the checks
would score it normally, and the published bundle would report a model that never had to
reason about anything.

That failure is invisible at runtime, so it is caught statically instead, in the same
defence-by-static-check style as the numeric lint in `policy/loader.py`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROVIDERS_DIR = Path(__file__).resolve().parents[2] / "src" / "credit_audit" / "model" / "providers"

FORBIDDEN_ATTRIBUTE = "env_state"


def _provider_sources() -> list[Path]:
    return sorted(PROVIDERS_DIR.glob("*.py"))


def test_the_providers_package_actually_has_files():
    """Guards the guard: a glob that matched nothing would make every test below vacuous."""

    sources = _provider_sources()
    assert sources
    assert {path.name for path in sources} >= {"openai_compat.py", "pricing.py"}


@pytest.mark.parametrize("path", _provider_sources(), ids=lambda p: p.name)
def test_no_adapter_reads_env_state(path: Path):
    """Parsed rather than grepped, so a comment mentioning the field is not a false positive
    and `getattr(req, "env_state")` is not a false negative."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offences: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == FORBIDDEN_ATTRIBUTE:
            offences.append(f"{path.name}:{node.lineno} attribute access .{FORBIDDEN_ATTRIBUTE}")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == FORBIDDEN_ATTRIBUTE
        ):
            offences.append(f"{path.name}:{node.lineno} getattr(..., {FORBIDDEN_ATTRIBUTE!r})")
        elif isinstance(node, ast.Constant) and node.value == FORBIDDEN_ATTRIBUTE:
            # A bare string literal is how a dynamic lookup would smuggle it past the checks
            # above. Docstrings are ast.Constant too, but never equal to the field name alone.
            offences.append(f"{path.name}:{node.lineno} string literal {FORBIDDEN_ATTRIBUTE!r}")

    assert not offences, (
        "a provider adapter must see only rendered text and tool results, exactly as a hosted "
        "model would: " + "; ".join(offences)
    )


def test_the_check_would_catch_a_violation(tmp_path):
    """A static check nobody has seen fail is a static check nobody knows works."""

    offender = tmp_path / "sneaky.py"
    offender.write_text("def f(req):\n    return req.env_state.applicant.facts\n")

    tree = ast.parse(offender.read_text())
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == FORBIDDEN_ATTRIBUTE
    ]
    assert found, "the detector must fire on a direct attribute read"


def test_the_check_would_catch_a_dynamic_lookup(tmp_path):
    offender = tmp_path / "sneakier.py"
    offender.write_text('def f(req):\n    return getattr(req, "env_state")\n')

    tree = ast.parse(offender.read_text())
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value == FORBIDDEN_ATTRIBUTE
    ]
    assert found, "the detector must fire on a string-based lookup"
