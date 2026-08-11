"""``RENDERERS: dict[RenderMode, Renderer]`` -- the dispatch table Phase 2's episode loop
(and every render-mode-parametrized test) uses instead of importing table/prose/json_
directly."""

from __future__ import annotations

from credit_audit.env.types import Renderer
from credit_audit.policy.loader import Policy
from credit_audit.render import json_ as _json_renderer
from credit_audit.render import prose as _prose_renderer
from credit_audit.render import table as _table_renderer
from credit_audit.render.packet import RenderOptions
from credit_audit.types import Applicant, RenderMode

RENDERERS: dict[RenderMode, Renderer] = {
    RenderMode.TABLE: _table_renderer.render,
    RenderMode.PROSE: _prose_renderer.render,
    RenderMode.JSON: _json_renderer.render,
}


def render_application(
    applicant: Applicant,
    mode: RenderMode,
    policy: Policy,
    *,
    options: RenderOptions | None = None,
) -> str:
    """Render through the public registry, including render-layer controls."""

    if mode is RenderMode.JSON:
        return _json_renderer.render(applicant, mode, policy, options=options)
    return RENDERERS[mode](applicant, mode, policy)


__all__ = ["RENDERERS", "render_application"]
