"""Canonical intervention application and immutable paired experiment plans."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from pydantic import model_validator

from credit_audit.ids import applicant_content_id, cluster_id_for, content_id, derive_seed
from credit_audit.render.packet import RenderOptions
from credit_audit.types import (
    Applicant,
    Family,
    Frozen,
    InterventionSpec,
    Layer,
    Relation,
    RenderMode,
)


class InterventionError(ValueError):
    """An intervention violates its declared layer or absolute-target contract."""


class AppliedInterventions(Frozen):
    applicant: Applicant
    render_options: RenderOptions = RenderOptions()
    intervention_ids: tuple[str, ...] = ()


class ArmPlan(Frozen):
    arm_id: str
    applicant: Applicant
    render_mode: RenderMode
    interventions: tuple[InterventionSpec, ...] = ()

    @property
    def intervention_ids(self) -> tuple[str, ...]:
        return tuple(spec.intervention_id for spec in self.interventions)

    def materialize(self) -> AppliedInterventions:
        return apply_interventions(self.applicant, self.interventions)


class PairPlan(Frozen):
    pair_id: str
    cluster_id: str
    seed_group: str
    check: str
    family: Family
    relation: Relation
    base: ArmPlan
    cf: ArmPlan

    @model_validator(mode="after")
    def _same_experimental_unit(self) -> PairPlan:
        if self.base.applicant.applicant_id != self.cf.applicant.applicant_id:
            raise ValueError("paired arms must retain the same stable applicant_id")
        if self.base.arm_id == self.cf.arm_id:
            raise ValueError("paired arms require distinct arm_id values")
        expected_cluster = cluster_id_for(self.base.applicant)
        if self.cluster_id != expected_cluster or self.cluster_id != cluster_id_for(
            self.cf.applicant
        ):
            raise ValueError("PairPlan cluster_id must identify the shared source applicant")
        expected_pair = pair_id_for_plan(
            self.base.applicant,
            self.check,
            self.base,
            self.cf,
            family=self.family,
            relation=self.relation,
            seed_group=self.seed_group,
        )
        if self.pair_id != expected_pair:
            raise ValueError("PairPlan pair_id does not match its canonical contrast identity")
        interventions = (*self.base.interventions, *self.cf.interventions)
        if any(spec.family is not self.family for spec in interventions):
            raise ValueError("every arm intervention must belong to the PairPlan family")
        if any(spec.expected_relation is not self.relation for spec in interventions):
            raise ValueError("every arm intervention must declare the PairPlan relation")
        by_id: dict[str, InterventionSpec] = {}
        for spec in interventions:
            previous = by_id.setdefault(spec.intervention_id, spec)
            if previous != spec:
                raise ValueError("duplicate intervention id has conflicting specs across arms")
        return self

    def trial_seed(self, run_seed: int, trial_index: int) -> int:
        """Common random number: corresponding arms receive the exact same seed."""

        if trial_index < 0:
            raise ValueError("trial_index must be non-negative")
        return derive_seed(run_seed, self.seed_group, trial_index)


def pair_id_for_plan(
    applicant: Applicant,
    check: str,
    base: ArmPlan,
    cf: ArmPlan,
    *,
    family: Family,
    relation: Relation,
    seed_group: str,
) -> str:
    return content_id(
        {
            "applicant_id": applicant.applicant_id,
            "base_applicant_content_id": applicant_content_id(base.applicant),
            "cf_applicant_content_id": applicant_content_id(cf.applicant),
            "check": check,
            "family": family,
            "relation": relation,
            "seed_group": seed_group,
            "base_arm_id": base.arm_id,
            "cf_arm_id": cf.arm_id,
            "base_interventions": base.interventions,
            "cf_interventions": cf.interventions,
            "base_render": base.render_mode,
            "cf_render": cf.render_mode,
        }
    )


def make_pair_plan(
    *,
    applicant: Applicant,
    check: str,
    family: Family,
    relation: Relation,
    base_arm_id: str,
    cf_arm_id: str,
    base_render_mode: RenderMode = RenderMode.TABLE,
    cf_render_mode: RenderMode = RenderMode.TABLE,
    base_interventions: tuple[InterventionSpec, ...] = (),
    cf_interventions: tuple[InterventionSpec, ...] = (),
    seed_group: str | None = None,
) -> PairPlan:
    base = ArmPlan(
        arm_id=base_arm_id,
        applicant=applicant,
        render_mode=base_render_mode,
        interventions=base_interventions,
    )
    cf = ArmPlan(
        arm_id=cf_arm_id,
        applicant=applicant,
        render_mode=cf_render_mode,
        interventions=cf_interventions,
    )
    effective_seed_group = seed_group or content_id(
        {
            "purpose": "paired-common-random-numbers",
            "applicant_id": applicant.applicant_id,
            "base_applicant_content_id": applicant_content_id(base.applicant),
            "cf_applicant_content_id": applicant_content_id(cf.applicant),
            "check": check,
            "family": family,
            "relation": relation,
            "base_arm_id": base.arm_id,
            "cf_arm_id": cf.arm_id,
            "base_interventions": base.interventions,
            "cf_interventions": cf.interventions,
            "base_render": base.render_mode,
            "cf_render": cf.render_mode,
        }
    )
    return PairPlan(
        pair_id=pair_id_for_plan(
            applicant,
            check,
            base,
            cf,
            family=family,
            relation=relation,
            seed_group=effective_seed_group,
        ),
        cluster_id=cluster_id_for(applicant),
        seed_group=effective_seed_group,
        check=check,
        family=family,
        relation=relation,
        base=base,
        cf=cf,
    )


def _targets(spec: InterventionSpec) -> dict[str, Any]:
    raw_targets = spec.params.get("targets")
    if not isinstance(raw_targets, Mapping) or not raw_targets:
        raise InterventionError(
            f"{spec.intervention_id}: {spec.layer.value} intervention requires non-empty "
            "params.targets with absolute values"
        )
    targets = dict(raw_targets)
    if spec.target_field is not None and spec.target_field not in targets:
        raise InterventionError(
            f"{spec.intervention_id}: target_field={spec.target_field!r} missing from targets"
        )
    return targets


def _validate_direction(spec: InterventionSpec, old: Any, new: Any, field: str) -> None:
    if spec.direction in {"set", "none"}:
        return
    if isinstance(old, bool) or isinstance(new, bool):
        raise InterventionError(f"{spec.intervention_id}: cannot order boolean field {field}")
    try:
        holds = new > old if spec.direction == "increase" else new < old
    except TypeError as exc:
        raise InterventionError(
            f"{spec.intervention_id}: direction {spec.direction} requires ordered values "
            f"for {field}"
        ) from exc
    if not holds:
        raise InterventionError(
            f"{spec.intervention_id}: absolute target for {field} does not {spec.direction} "
            f"the value ({old!r} -> {new!r})"
        )


def _append_lineage(applicant: Applicant, intervention_id: str) -> Applicant:
    lineage = applicant.provenance.intervention_lineage
    if intervention_id in lineage:
        return applicant
    provenance = applicant.provenance.model_copy(
        update={"intervention_lineage": (*lineage, intervention_id)}
    )
    return applicant.model_copy(update={"provenance": provenance})


def _apply_model_layer(applicant: Applicant, spec: InterventionSpec) -> Applicant:
    if spec.layer is Layer.FACTS:
        current = applicant.facts
        other_before = content_id(applicant.presentation)
    elif spec.layer is Layer.PRESENTATION:
        current = applicant.presentation
        other_before = content_id(applicant.facts)
    else:  # pragma: no cover - registry routes this away
        raise AssertionError(spec.layer)

    targets = _targets(spec)
    unknown = set(targets) - set(type(current).model_fields)
    if unknown:
        raise InterventionError(
            f"{spec.intervention_id}: fields do not belong to {spec.layer.value}: {sorted(unknown)}"
        )

    # Validate rather than model_copy(update=...), which intentionally skips validation.
    payload = current.model_dump(mode="python")
    payload.update(targets)
    changed = type(current).model_validate(payload)

    if spec.intervention_id in applicant.provenance.intervention_lineage:
        if changed != current:
            raise InterventionError(
                f"{spec.intervention_id}: intervention id was already applied with other targets"
            )
        return applicant

    for field, new in targets.items():
        _validate_direction(spec, getattr(current, field), new, field)

    field_name = "facts" if spec.layer is Layer.FACTS else "presentation"
    result = applicant.model_copy(update={field_name: changed})
    result = _append_lineage(result, spec.intervention_id)
    other_after = content_id(result.presentation if spec.layer is Layer.FACTS else result.facts)
    if other_before != other_after:
        raise InterventionError(f"{spec.intervention_id}: crossed the declared layer boundary")
    return result


def _apply_render_layer(applicant: Applicant, spec: InterventionSpec) -> Applicant:
    if spec.target_field not in {None, "json_field_order_seed"}:
        raise InterventionError(
            f"{spec.intervention_id}: unsupported render target {spec.target_field!r}"
        )
    options = spec.params.get("options")
    if not isinstance(options, Mapping) or not options:
        raise InterventionError(
            f"{spec.intervention_id}: render intervention requires params.options"
        )
    unknown = set(options) - set(RenderOptions.model_fields)
    if unknown:
        raise InterventionError(
            f"{spec.intervention_id}: unsupported render options {sorted(unknown)}"
        )
    if spec.target_field is not None and spec.target_field not in options:
        raise InterventionError(
            f"{spec.intervention_id}: target_field={spec.target_field!r} missing from options"
        )
    RenderOptions.model_validate(dict(options))
    return _append_lineage(applicant, spec.intervention_id)


_APPLIERS: dict[Layer, Callable[[Applicant, InterventionSpec], Applicant]] = {
    Layer.FACTS: _apply_model_layer,
    Layer.PRESENTATION: _apply_model_layer,
    Layer.RENDER: _apply_render_layer,
}


def apply_intervention(applicant: Applicant, spec: InterventionSpec) -> Applicant:
    """Apply one validated absolute intervention through the layer registry."""

    try:
        applier = _APPLIERS[spec.layer]
    except KeyError as exc:  # pragma: no cover - enum currently exhaustive
        raise InterventionError(f"unsupported intervention layer: {spec.layer}") from exc
    return applier(applicant, spec)


def apply_interventions(
    applicant: Applicant, specs: tuple[InterventionSpec, ...]
) -> AppliedInterventions:
    """Materialize an arm, merging render options and preserving declared order."""

    current = applicant
    render_payload: dict[str, Any] = {}
    applied_specs: dict[str, InterventionSpec] = {}
    for spec in specs:
        previous = applied_specs.get(spec.intervention_id)
        if previous is not None:
            if previous != spec:
                raise InterventionError(
                    f"{spec.intervention_id}: duplicate intervention id has conflicting specs"
                )
            continue
        applied_specs[spec.intervention_id] = spec
        current = apply_intervention(current, spec)
        if spec.layer is Layer.RENDER:
            render_payload.update(dict(spec.params["options"]))
    return AppliedInterventions(
        applicant=current,
        render_options=RenderOptions.model_validate(render_payload),
        intervention_ids=tuple(applied_specs),
    )


__all__ = [
    "AppliedInterventions",
    "ArmPlan",
    "InterventionError",
    "PairPlan",
    "apply_intervention",
    "apply_interventions",
    "cluster_id_for",
    "make_pair_plan",
    "pair_id_for_plan",
]
