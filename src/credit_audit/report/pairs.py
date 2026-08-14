"""Pair detail -- the screen that shows the causal test actually ran.

This is the drill-down the whole design points at: one applicant, one field changed, both arms
executed under the same seed, and every message, tool call, and decision on both sides. The
frontend authors no prose; every string a reader sees is produced here.

Two things are deliberate.

**The held-out reason is a first-class field.** On a leave-one-out necessity test, one reason
is deliberately *not* repaired, and a reader who misses that misunderstands the entire test.
It travels as ``hypothesis.held_out_code`` so the UI can render it distinctly rather than
leaving it to be inferred from a diff.

**The system prompt is not repeated.** It is roughly 12 KB and identical across every episode
in a run, so it is deduplicated into ``prompts/<hash>.json`` and each trial carries a
``prompt_ref``. That is the difference between a bundle that fits its size budget and one that
does not.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel

from credit_audit.ids import applicant_content_id, content_id
from credit_audit.policy.loader import Policy
from credit_audit.policy.oracle import evaluate
from credit_audit.reasons.codes import CODE_META, ReasonCode
from credit_audit.report.catalog import prose_for
from credit_audit.report.summary import verdict_for
from credit_audit.types import (
    Applicant,
    InterventionRecord,
    InterventionSpec,
    Layer,
    Message,
    TestResult,
    Trajectory,
)

PAIR_SCHEMA = "credit-audit/pair@1"

PAIRS_DIR = "pairs"
PROMPTS_DIR = "prompts"


def pair_file_for(pair_id: str) -> str:
    return f"{PAIRS_DIR}/{_slug(pair_id)}.json"


def prompt_file_for(prompt_hash: str) -> str:
    return f"{PROMPTS_DIR}/{_slug(prompt_hash)}.json"


def _slug(identifier: str) -> str:
    """Content ids carry a ``blake2b128:`` prefix; a colon is not a portable filename."""

    return identifier.replace(":", "_")


def _facts_payload(applicant: Applicant, policy: Policy) -> dict[str, Any]:
    facts = applicant.facts
    decision = evaluate(facts, policy)
    return {
        "facts": {name: _scalar(getattr(facts, name)) for name in sorted(type(facts).model_fields)},
        # Derived quantities are properties, never stored fields. Shown explicitly so the
        # question "did you leave a stale ratio behind after repairing income?" is answered on
        # the page rather than in a docstring.
        "derived": {
            "dti": str(facts.dti),
            "cltv": str(facts.cltv),
            "utilization": str(facts.utilization),
        },
        "presentation": {
            name: _scalar(getattr(applicant.presentation, name))
            for name in sorted(type(applicant.presentation).model_fields)
        },
        "oracle": {
            "breached": sorted({str(code) for code in decision.breached_codes}),
            "decision": str(decision.outcome),
        },
    }


def _scalar(value: Any) -> Any:
    """JSON-safe projection for the pair viewer.

    Deliberately separate from ``ids.portable_json``: this one keeps ``Decimal`` as a string
    so a ratio renders exactly as the policy compares it, rather than acquiring a float's
    rounding on the way to the page.
    """

    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, BaseModel):
        return {name: _scalar(getattr(value, name)) for name in sorted(type(value).model_fields)}
    if isinstance(value, (list, tuple)):
        return [_scalar(item) for item in value]
    if isinstance(value, Mapping):
        return {str(k): _scalar(v) for k, v in sorted(value.items())}
    return value


def _held_out_fields(check: str, held_out_code: str | None) -> frozenset[str]:
    """Which fact fields the deliberately-unrepaired reason code is carried by.

    The necessity test repairs every breach *except* one, so the reader has to be able to see
    which row is the one left alone -- the roadmap requires it to carry its own glyph and the
    literal words "deliberately not repaired", and a reader who misses it misreads the whole
    test. ``CODE_META[code].target_fields`` already maps a reason code to the fields that repair
    it, so nothing new needs deriving.

    Restricted to the necessity check on purpose. ``public_records`` backs two different codes,
    and outside necessity a matching field name means nothing.
    """

    if not held_out_code or not check.endswith("necessity_loo"):
        return frozenset()
    try:
        meta = CODE_META[ReasonCode(held_out_code)]
    except (KeyError, ValueError):  # pragma: no cover - observed codes are always in the enum
        return frozenset()
    return frozenset(meta.target_fields)


def _diff(
    base: Applicant,
    cf: Applicant,
    *,
    check: str = "",
    held_out_code: str | None = None,
    intervention_ids: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Every field that differs, tagged with the layer it belongs to.

    The facts/presentation split is structural in the type system; surfacing which layer each
    change touched turns that guarantee into something a reader can check by eye.
    """

    held_out_fields = _held_out_fields(check, held_out_code)
    by_field = dict(intervention_ids or {})
    entries: list[dict[str, Any]] = []
    for layer, holder in ((Layer.FACTS, "facts"), (Layer.PRESENTATION, "presentation")):
        before_obj = getattr(base, holder)
        after_obj = getattr(cf, holder)
        for name in sorted(type(before_obj).model_fields):
            before = getattr(before_obj, name)
            after = getattr(after_obj, name)
            if before == after:
                continue
            entries.append(
                {
                    "path": f"{holder}.{name}",
                    "before": _scalar(before),
                    "after": _scalar(after),
                    "layer": layer.value,
                    "display": f"{name}: {_scalar(before)} -> {_scalar(after)}",
                    "intervention_id": by_field.get(name),
                    # The observed sign, not the spec's ``direction``: every intervention
                    # builder in the repo passes "set", so the declared field says nothing.
                    "direction": _observed_direction(before, after),
                    "held_out": holder == "facts" and name in held_out_fields,
                }
            )
    return entries


def _observed_direction(before: Any, after: Any) -> str | None:
    """Which way a field moved, for readers scanning a diff column."""

    if isinstance(before, bool) or isinstance(after, bool):
        return "set"
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        if after > before:
            return "increase"
        if after < before:
            return "decrease"
        return "set"
    return "set"


def _contributions(result: TestResult, estimates_doc: Mapping[str, Any] | None) -> list[dict]:
    """Which published statistics this pair fed.

    Without it a pair page reads as an anecdote somebody chose. Every check builds
    ``test_id == pair_id``, so the link is a lookup against each estimate's
    ``support_test_ids`` rather than anything new.

    ``pass_k`` is deliberately absent: it publishes only aggregates and records no unit ids, so
    claiming this pair fed it would be an assertion rather than a lookup.
    """

    if not estimates_doc:
        return []
    contributions = [
        {
            "estimate_id": estimate["estimate_id"],
            "role": f"{estimate.get('estimand', '')}/{estimate.get('stratum', '')}".strip("/"),
            "cluster_id": result.cluster_id,
        }
        for estimate in estimates_doc.get("estimates", ())
        if result.test_id in estimate.get("support_test_ids", ())
    ]
    return sorted(contributions, key=lambda row: row["estimate_id"])


def _hashes(base: Applicant, cf: Applicant) -> dict[str, Any]:
    facts_base = content_id(base.facts)
    facts_cf = content_id(cf.facts)
    presentation_base = content_id(base.presentation)
    presentation_cf = content_id(cf.presentation)
    return {
        "facts_base": facts_base,
        "facts_cf": facts_cf,
        "presentation_base": presentation_base,
        "presentation_cf": presentation_cf,
        # Rendered as a visible check: a presentation-layer contrast must leave the facts hash
        # bit-identical, and vice versa. The structural guarantee becomes observable.
        "presentation_identical": presentation_base == presentation_cf,
        "facts_identical": facts_base == facts_cf,
    }


def _message_payload(message: Message, *, prompt_ref: str | None) -> dict[str, Any]:
    content = message.content
    if prompt_ref is not None and message.role == "system":
        content = ""
    return {
        "role": message.role,
        "content": content,
        "step": message.step,
        "turn_index": message.turn_index,
        "tool_call_id": message.tool_call_id,
        "tool_calls": [
            {
                "call_id": call.call_id,
                "name": call.name,
                "arguments": _scalar(dict(call.arguments)),
            }
            for call in message.tool_calls
        ],
    }


def _trial_payload(trajectory: Trajectory, *, prompt_ref: str) -> dict[str, Any]:
    key = trajectory.key
    return {
        "trial_index": key.trial_index,
        "seed": key.seed,
        "episode_id": trajectory.episode_id,
        "trajectory_id": trajectory.trajectory_id,
        "applicant_content_id": key.applicant_content_id,
        "prompt_hash": key.prompt_hash,
        "input_hash": key.input_hash,
        "prompt_ref": prompt_ref,
        "render": key.render_id.value,
        "arm": key.arm_id,
        "termination": trajectory.termination.value,
        "final_state_hash": trajectory.final_state_hash,
        "messages": [_message_payload(m, prompt_ref=prompt_ref) for m in trajectory.messages],
        "tool_calls": [
            {
                "call_id": call.call_id,
                "turn_index": call.turn_index,
                "step": call.step,
                "name": call.name,
                "arguments": _scalar(dict(call.arguments)),
                "result": _scalar(dict(call.result)),
                "ok": call.ok,
                "error": call.error,
                "latency_ms": call.latency_ms,
            }
            for call in trajectory.tool_calls
        ],
        "decision": _scalar(trajectory.decision) if trajectory.decision else None,
        "usage": _scalar(trajectory.usage),
    }


def _side_payload(trajectories: tuple[Trajectory, ...], *, prompt_refs: dict[str, str]) -> dict:
    from credit_audit.checks.paired import OutcomeClass, classify_trajectory

    ordered = sorted(trajectories, key=lambda t: t.key.trial_index)
    decisive = [classify_trajectory(t) for t in ordered]
    scored = [outcome for outcome in decisive if outcome is not OutcomeClass.NO_DECISION]
    approvals = sum(1 for outcome in scored if outcome is OutcomeClass.APPROVE)
    return {
        "trials": [_trial_payload(t, prompt_ref=prompt_refs[t.key.prompt_hash]) for t in ordered],
        "approve_rate": (approvals / len(scored)) if scored else 0.0,
    }


def _spec_payload(spec: InterventionSpec, *, arm: str) -> dict[str, Any]:
    return {
        "arm": arm,
        "intervention_id": spec.intervention_id,
        "family": str(spec.family),
        "name": spec.name,
        "layer": spec.layer.value,
        "target_field": spec.target_field,
        "direction": spec.direction,
        "expected_relation": str(spec.expected_relation),
        "params": _scalar(dict(spec.params)),
    }


def _applied_interventions(
    base_trajectories: tuple[Trajectory, ...],
    cf_trajectories: tuple[Trajectory, ...],
    interventions: Mapping[tuple[str, str], InterventionRecord] | None,
    base_content_id: str,
    cf_content_id: str,
) -> list[dict[str, Any]]:
    """What each arm actually did, read from the run's recorded intervention evidence.

    Eight of the exported pairs have an empty applicant diff because their contrast is field
    ordering or serialization format rather than a fact -- for those this is the *only* place
    the contrast appears at all, which is why an empty list here was not a cosmetic gap.

    Empty for a run recorded before ``interventions.jsonl`` existed, rather than reconstructed:
    guessing what an old run did and publishing it as observation is exactly the move this
    bundle exists to avoid.
    """

    if not interventions:
        return []
    payload: list[dict[str, Any]] = []
    for arm, trajectories, content_id_ in (
        ("base", base_trajectories, base_content_id),
        ("cf", cf_trajectories, cf_content_id),
    ):
        if not trajectories:
            continue
        record = interventions.get((trajectories[0].key.arm_id, content_id_))
        if record is None:
            continue
        payload.extend(_spec_payload(spec, arm=arm) for spec in record.interventions)
    return payload


def _intervention_ids_by_field(applied: list[dict[str, Any]]) -> dict[str, str]:
    """Map a changed fact field back to the intervention that changed it.

    Counterfactual repairs name every field they touch in ``params.targets``; simple
    interventions name one in ``target_field``. Later arms win, which is what the reader wants:
    the cf leg is the one that moved the value they are looking at.
    """

    by_field: dict[str, str] = {}
    for spec in applied:
        target = spec.get("target_field")
        if isinstance(target, str) and target:
            by_field[target] = spec["intervention_id"]
        targets = (spec.get("params") or {}).get("targets")
        if isinstance(targets, Mapping):
            for field in targets:
                by_field[str(field)] = spec["intervention_id"]
    return by_field


def build_pair(
    result: TestResult,
    *,
    run_id: str,
    base_trajectories: tuple[Trajectory, ...],
    cf_trajectories: tuple[Trajectory, ...],
    applicants: dict[str, Applicant],
    policy: Policy,
    prompt_refs: dict[str, str],
    estimates_doc: Mapping[str, Any] | None = None,
    interventions: Mapping[tuple[str, str], InterventionRecord] | None = None,
) -> dict[str, Any]:
    prose = prose_for(result.check)
    base_content_id = base_trajectories[0].key.applicant_content_id if base_trajectories else ""
    cf_content_id = cf_trajectories[0].key.applicant_content_id if cf_trajectories else ""
    base_applicant = applicants.get(base_content_id)
    cf_applicant = applicants.get(cf_content_id)
    if base_applicant is None or cf_applicant is None:
        raise KeyError(
            f"pair {result.pair_id} references an applicant variant absent from the run "
            f"artifacts ({base_content_id!r} / {cf_content_id!r})"
        )

    observed = dict(result.observed)
    metrics = {
        column: observed.get(column)
        for column in (
            "planned_trials",
            "matched_trials",
            "base_completed",
            "cf_completed",
            "base_completion_rate",
            "cf_completion_rate",
            "bilateral_incomplete",
            "unilateral_incomplete",
            "pair_completion_rate",
            "base_approve_rate",
            "cf_approve_rate",
            "effect",
            "adverse_to_approve",
            "approve_to_adverse",
            "reason_signature_changes",
            "decision_signature_changes",
        )
    }

    # ``omitted_code`` is the omission scan's name for the same thing. The old fallback read
    # ``isolated_code``, a key nothing has ever written, so omission pairs published a null
    # here; invisible until a run actually produced one.
    held_out = observed.get("held_out_code") or observed.get("omitted_code")
    applied = _applied_interventions(
        base_trajectories, cf_trajectories, interventions, base_content_id, cf_content_id
    )

    return {
        "schema": PAIR_SCHEMA,
        "pair_id": result.pair_id,
        "cluster_id": result.cluster_id,
        "seed_group": str(observed.get("seed_group", "")),
        "run_id": run_id,
        "test_id": result.test_id,
        "check": result.check,
        "family": str(result.family),
        "status": result.status.value,
        "verdict": verdict_for(result.status),
        "hypothesis": {
            "expected": result.expected or prose.question,
            "observed": result.notes or f"status={result.status.value}",
            "plain_english": prose.failure_means,
            "formal": prose.question,
            "held_out_code": str(held_out) if held_out else None,
        },
        "applicant": {
            "applicant_id": result.applicant_id,
            "base_content_id": base_content_id,
            "cf_content_id": cf_content_id,
            "base": _facts_payload(base_applicant, policy),
            "cf": _facts_payload(cf_applicant, policy),
            "diff": _diff(
                base_applicant,
                cf_applicant,
                check=result.check,
                held_out_code=str(held_out) if held_out else None,
                intervention_ids=_intervention_ids_by_field(applied),
            ),
            "unchanged_facts_count": sum(
                1
                for name in type(base_applicant.facts).model_fields
                if getattr(base_applicant.facts, name) == getattr(cf_applicant.facts, name)
            ),
            "hashes": _hashes(base_applicant, cf_applicant),
        },
        "interventions": applied,
        "metrics": metrics,
        "sides": {
            "base": _side_payload(base_trajectories, prompt_refs=prompt_refs),
            "cf": _side_payload(cf_trajectories, prompt_refs=prompt_refs),
        },
        "contributes_to": _contributions(result, estimates_doc),
        "provenance": {"source_lines": {}, "truncated": False},
    }


def collect_prompts(trajectories: tuple[Trajectory, ...]) -> dict[str, str]:
    """Deduplicate system prompts by their recorded hash.

    The prompt is the largest repeated string in a run by an order of magnitude. Storing it
    once and referencing it is the single biggest size win the bundle has.
    """

    prompts: dict[str, str] = {}
    for trajectory in trajectories:
        prompt_hash = trajectory.key.prompt_hash
        if prompt_hash in prompts:
            continue
        for message in trajectory.messages:
            if message.role == "system":
                prompts[prompt_hash] = message.content
                break
    return prompts


def applicant_index(applicants: tuple[Applicant, ...]) -> dict[str, Applicant]:
    return {applicant_content_id(applicant): applicant for applicant in applicants}


__all__ = [
    "PAIRS_DIR",
    "PAIR_SCHEMA",
    "PROMPTS_DIR",
    "applicant_index",
    "build_pair",
    "collect_prompts",
    "pair_file_for",
    "prompt_file_for",
]
