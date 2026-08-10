"""Environment-local types: tool schemas and the rendering seam.

``Renderer`` is the entire contract between this package and Phase 3's `render/` package.
Nothing in `env/` imports from `render/`, and nothing in `render/` needs to import from
`env/` beyond conforming to this one signature -- Phase 3 ships without touching a file
here.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from credit_audit.policy.loader import Policy
from credit_audit.types import Applicant, Frozen, RenderMode

Renderer = Callable[[Applicant, RenderMode, Policy], str]
"""(applicant, render_mode, policy) -> the application text the agent is shown.
Phase 3's render/table.py, render/prose.py, render/json_.py each conform to this."""


class ToolSpec(Frozen):
    name: str
    description: str
    parameters: dict[str, Any]
    """JSON Schema for the tool's arguments. Validated via jsonschema.validate before the
    tool function is ever invoked -- see env.tools.dispatch."""


class ToolResult(Frozen):
    data: dict[str, Any]
    ok: bool = True
    error: str | None = None


__all__ = ["Renderer", "ToolResult", "ToolSpec"]
