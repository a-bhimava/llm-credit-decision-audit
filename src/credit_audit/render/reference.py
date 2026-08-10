"""Applicant reference derivation -- the renderer's only source for an in-text application ID.

Phase 2's ``_fetch_credit_report`` deferred "how ``applicant_ref`` is embedded in rendered
text" to Phase 3. The frozen ``Renderer`` signature (``Callable[[Applicant, RenderMode,
Policy], str]``) settles it: a renderer has no external ref parameter to embed, so it derives
one from the ``Applicant`` it already has. Whatever later phase wires
``CreditEnvState.applicant_ref`` must call this same function, so the two can never textually
disagree -- see ``tests/unit/render/test_reference.py``.
"""

from __future__ import annotations

from credit_audit.ids import content_id
from credit_audit.types import Applicant


def applicant_reference(applicant_id: str) -> str:
    """Deterministic, derived from public content (the applicant_id itself) -- adds no new
    leak surface. ``blake2b128:<32 hex>`` -> ``MPL-<first 10 hex, uppercased>``."""
    digest = content_id(applicant_id, digest_size=16)
    hex_part = digest.split(":", 1)[1]
    return f"MPL-{hex_part[:10].upper()}"


def applicant_reference_for(applicant: Applicant) -> str:
    return applicant_reference(applicant.applicant_id)


__all__ = ["applicant_reference", "applicant_reference_for"]
