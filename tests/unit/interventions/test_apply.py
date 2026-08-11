from __future__ import annotations

import pytest

from credit_audit.checks.runner import paired_trial_seed
from credit_audit.ids import cluster_id_for, content_id
from credit_audit.interventions.apply import (
    InterventionError,
    PairPlan,
    apply_intervention,
    apply_interventions,
    make_pair_plan,
)
from credit_audit.types import Family, InterventionSpec, Layer, Relation, RenderMode


def _spec(*, layer, targets=None, options=None, direction="set", target_field=None):
    params = {"options": options} if layer is Layer.RENDER else {"targets": targets}
    return InterventionSpec(
        intervention_id=f"test-{layer.value}-{target_field or 'composite'}",
        family=Family.INVARIANCE,
        name="test",
        layer=layer,
        target_field=target_field,
        direction=direction,
        expected_relation=Relation.INVARIANT,
        params=params,
    )


def test_presentation_intervention_preserves_facts_and_is_idempotent(golden_clean_applicant):
    spec = _spec(
        layer=Layer.PRESENTATION,
        targets={"applicant_name": "Visible Name", "school": "Visible School"},
    )
    changed = apply_intervention(golden_clean_applicant, spec)
    assert content_id(changed.facts) == content_id(golden_clean_applicant.facts)
    assert changed.presentation.applicant_name == "Visible Name"
    assert changed.provenance.intervention_lineage[-1] == spec.intervention_id
    assert apply_intervention(changed, spec) == changed


def test_facts_intervention_preserves_presentation_and_validates_direction(
    golden_clean_applicant,
):
    good = _spec(
        layer=Layer.FACTS,
        targets={"credit_score": 760},
        direction="increase",
        target_field="credit_score",
    )
    changed = apply_intervention(golden_clean_applicant, good)
    assert content_id(changed.presentation) == content_id(golden_clean_applicant.presentation)
    assert changed.facts.credit_score == 760
    assert apply_intervention(changed, good) == changed

    bad = _spec(
        layer=Layer.FACTS,
        targets={"credit_score": 700},
        direction="increase",
        target_field="credit_score",
    )
    with pytest.raises(InterventionError, match="does not increase"):
        apply_intervention(golden_clean_applicant, bad)


def test_layer_registry_rejects_cross_layer_target(golden_clean_applicant):
    spec = _spec(layer=Layer.FACTS, targets={"applicant_name": "Nope"})
    with pytest.raises(InterventionError, match="do not belong to facts"):
        apply_intervention(golden_clean_applicant, spec)


def test_render_intervention_changes_options_not_semantic_layers(golden_clean_applicant):
    spec = _spec(
        layer=Layer.RENDER,
        options={"json_field_order_seed": 47},
        target_field="json_field_order_seed",
    )
    applied = apply_interventions(golden_clean_applicant, (spec,))
    assert content_id(applied.applicant.facts) == content_id(golden_clean_applicant.facts)
    assert content_id(applied.applicant.presentation) == content_id(
        golden_clean_applicant.presentation
    )
    assert applied.render_options.json_field_order_seed == 47


def test_render_intervention_validates_declared_target_field(golden_clean_applicant):
    spec = _spec(
        layer=Layer.RENDER,
        options={"json_field_order_seed": 47},
        target_field="missing_option",
    )
    with pytest.raises(InterventionError, match="unsupported render target"):
        apply_interventions(golden_clean_applicant, (spec,))

    spec = spec.model_copy(
        update={"target_field": "json_field_order_seed", "params": {"options": {}}}
    )
    with pytest.raises(InterventionError, match="requires params.options"):
        apply_interventions(golden_clean_applicant, (spec,))


def test_apply_interventions_deduplicates_identical_ids_and_rejects_conflicts(
    golden_clean_applicant,
):
    spec = _spec(
        layer=Layer.PRESENTATION,
        targets={"applicant_name": "Visible Name"},
        target_field="applicant_name",
    )
    applied = apply_interventions(golden_clean_applicant, (spec, spec))
    assert applied.intervention_ids == (spec.intervention_id,)
    assert applied.applicant.provenance.intervention_lineage == (spec.intervention_id,)

    conflict = spec.model_copy(update={"params": {"targets": {"applicant_name": "Different Name"}}})
    with pytest.raises(InterventionError, match="conflicting specs"):
        apply_interventions(golden_clean_applicant, (spec, conflict))


def test_pair_plan_has_common_seed_and_canonical_cluster(golden_clean_applicant):
    plan = make_pair_plan(
        applicant=golden_clean_applicant,
        check="invariance.test",
        family=Family.INVARIANCE,
        relation=Relation.INVARIANT,
        base_arm_id="base",
        cf_arm_id="cf",
        base_render_mode=RenderMode.TABLE,
        cf_render_mode=RenderMode.JSON,
    )
    assert plan.cluster_id == cluster_id_for(golden_clean_applicant)
    assert plan.trial_seed(123, 2) == paired_trial_seed(123, plan.seed_group, 2)
    assert plan.base.arm_id != plan.cf.arm_id

    with pytest.raises(ValueError, match="cluster_id"):
        PairPlan(**{**plan.model_dump(), "cluster_id": "cluster_tampered"})
    with pytest.raises(ValueError, match="pair_id"):
        PairPlan(**{**plan.model_dump(), "pair_id": "pair_tampered"})

    variant = golden_clean_applicant.model_copy(
        update={"facts": golden_clean_applicant.facts.model_copy(update={"credit_score": 739})}
    )
    variant_plan = make_pair_plan(
        applicant=variant,
        check="invariance.test",
        family=Family.INVARIANCE,
        relation=Relation.INVARIANT,
        base_arm_id="base",
        cf_arm_id="cf",
        base_render_mode=RenderMode.TABLE,
        cf_render_mode=RenderMode.JSON,
    )
    assert variant_plan.pair_id != plan.pair_id
    assert variant_plan.cluster_id == plan.cluster_id

    same_id_a = _spec(
        layer=Layer.PRESENTATION,
        targets={"applicant_name": "Variant A"},
        target_field="applicant_name",
    )
    same_id_b = same_id_a.model_copy(
        update={"params": {"targets": {"applicant_name": "Variant B"}}}
    )
    plan_a = make_pair_plan(
        applicant=golden_clean_applicant,
        check="invariance.full-spec-hash",
        family=Family.INVARIANCE,
        relation=Relation.INVARIANT,
        base_arm_id="base",
        cf_arm_id="cf",
        cf_interventions=(same_id_a,),
    )
    plan_b = make_pair_plan(
        applicant=golden_clean_applicant,
        check="invariance.full-spec-hash",
        family=Family.INVARIANCE,
        relation=Relation.INVARIANT,
        base_arm_id="base",
        cf_arm_id="cf",
        cf_interventions=(same_id_b,),
    )
    assert plan_a.pair_id != plan_b.pair_id
