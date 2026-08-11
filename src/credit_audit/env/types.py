"""Environment-local types: tool schemas and the rendering seam.

``Renderer`` is the callable contract implemented by each serializer. The canonical episode
builder imports the public render registry so input identity and visible text cannot drift;
renderer modules depend only on this small type surface from ``env``.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import Field

from credit_audit.policy.loader import Policy
from credit_audit.types import Applicant, Frozen, FrozenDict, RenderMode

Renderer = Callable[[Applicant, RenderMode, Policy], str]
"""(applicant, render_mode, policy) -> the application text the agent is shown.
Phase 3's render/table.py, render/prose.py, render/json_.py each conform to this."""


class ToolSpec(Frozen):
    name: str
    description: str
    parameters: FrozenDict
    """JSON Schema for the tool's arguments. Validated via jsonschema.validate before the
    tool function is ever invoked -- see env.tools.dispatch. The dispatcher explicitly
    thaws both schema and instance at that library boundary; the stored schema remains
    recursively immutable and hashable like every other evidence payload."""


class ToolResult(Frozen):
    data: FrozenDict = Field(default_factory=FrozenDict)
    ok: bool = True
    error: str | None = None


__all__ = ["Renderer", "ToolResult", "ToolSpec"]
