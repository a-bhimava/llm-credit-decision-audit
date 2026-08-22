import { Applicant, InterventionSpec, Layer, RenderMode } from "../records";
import { buildApplicant } from "../records";

export type AppliedInterventions = Readonly<{
  applicant: Applicant;
  render_options: Readonly<Record<string, unknown>>;
  intervention_ids: readonly string[];
}>;

function appendLineage(applicant: Applicant, interventionId: string): Applicant {
  const provenance = {
    ...applicant.provenance,
    intervention_lineage: [...applicant.provenance.intervention_lineage, interventionId],
  };
  return buildApplicant(
    applicant.applicant_id,
    applicant.facts,
    applicant.presentation,
    provenance
  );
}

function applyModelLayer(applicant: Applicant, spec: InterventionSpec): Applicant {
  const targets = (spec.params.targets || {}) as Record<string, unknown>;
  
  if (spec.layer === "facts") {
    const newFacts: any = { ...applicant.facts };
    for (const [k, v] of Object.entries(targets)) {
      if (!(k in newFacts)) throw new Error(`Invalid target field: ${k}`);
      newFacts[k] = v;
    }
    const provenance = {
      ...applicant.provenance,
      intervention_lineage: [...applicant.provenance.intervention_lineage, spec.intervention_id],
    };
    return buildApplicant(
      applicant.applicant_id,
      newFacts,
      applicant.presentation,
      provenance
    );
  } else if (spec.layer === "presentation") {
    const newPres: any = { ...applicant.presentation };
    for (const [k, v] of Object.entries(targets)) {
      if (k === "demographic_tags") {
        newPres[k] = Object.freeze({ ...newPres[k], ...(v as any) });
      } else {
        if (!(k in newPres)) throw new Error(`Invalid target field: ${k}`);
        newPres[k] = v;
      }
    }
    const provenance = {
      ...applicant.provenance,
      intervention_lineage: [...applicant.provenance.intervention_lineage, spec.intervention_id],
    };
    return buildApplicant(
      applicant.applicant_id,
      applicant.facts,
      newPres,
      provenance
    );
  } else {
    throw new Error(`Layer not handled: ${spec.layer}`);
  }
}

function applyRenderLayer(applicant: Applicant, spec: InterventionSpec): Applicant {
  // Render options are just passed through in AppliedInterventions
  return appendLineage(applicant, spec.intervention_id);
}

export function applyIntervention(applicant: Applicant, spec: InterventionSpec): Applicant {
  if (spec.direction !== "set") {
    throw new Error(`${spec.intervention_id}: only absolute set interventions can be applied`);
  }
  
  if (spec.layer === "facts" || spec.layer === "presentation") {
    return applyModelLayer(applicant, spec);
  } else if (spec.layer === "render") {
    return applyRenderLayer(applicant, spec);
  } else {
    throw new Error(`unsupported intervention layer: ${spec.layer}`);
  }
}

export function applyInterventions(applicant: Applicant, specs: readonly InterventionSpec[]): AppliedInterventions {
  let current = applicant;
  const renderPayload: any = {};
  const appliedSpecs: Record<string, InterventionSpec> = {};
  
  for (const spec of specs) {
    if (appliedSpecs[spec.intervention_id]) {
      // ignore duplicates, but wait python throws if they have conflicting specs
      continue;
    }
    appliedSpecs[spec.intervention_id] = spec;
    current = applyIntervention(current, spec);
    if (spec.layer === "render") {
      const opts = (spec.params.options || {}) as Record<string, unknown>;
      Object.assign(renderPayload, opts);
    }
  }
  
  return Object.freeze({
    applicant: current,
    render_options: Object.freeze(renderPayload),
    intervention_ids: Object.freeze(Object.keys(appliedSpecs)),
  });
}

export type ArmPlan = Readonly<{
  arm_id: string;
  applicant: Applicant;
  render_mode: RenderMode;
  interventions: readonly InterventionSpec[];
}>;

export type PairPlan = Readonly<{
  pair_id: string;
  cluster_id: string;
  seed_group: string;
  check: string;
  family: Family;
  relation: Relation;
  base: ArmPlan;
  cf: ArmPlan;
}>;

import { contentId, applicantContentId, shortId } from "../ids";
import { Family, Relation } from "../records";

export function clusterIdFor(applicant: Applicant): string {
  const root = applicant.provenance.parent_applicant_id || applicant.applicant_id;
  return `cluster_${shortId({ source_applicant_id: root }, 16)}`;
}

export function pairIdForPlan(opts: {
  check: string;
  baseArmId: string;
  cfArmId: string;
  baseInterventionIds: readonly string[];
  cfInterventionIds: readonly string[];
}): string {
  return contentId({
    check: opts.check,
    base_arm_id: opts.baseArmId,
    cf_arm_id: opts.cfArmId,
    base_intervention_ids: opts.baseInterventionIds,
    cf_intervention_ids: opts.cfInterventionIds,
  });
}

export function makePairPlan(opts: {
  applicant: Applicant;
  check: string;
  family: Family;
  relation: Relation;
  baseArmId: string;
  cfArmId: string;
  baseRenderMode?: RenderMode;
  cfRenderMode?: RenderMode;
  baseInterventions?: readonly InterventionSpec[];
  cfInterventions?: readonly InterventionSpec[];
  seedGroup?: string;
}): PairPlan {
  const baseRenderMode = opts.baseRenderMode || ("table" as RenderMode);
  const cfRenderMode = opts.cfRenderMode || ("table" as RenderMode);
  const baseInterventions = opts.baseInterventions || [];
  const cfInterventions = opts.cfInterventions || [];
  
  const base: ArmPlan = Object.freeze({
    arm_id: opts.baseArmId,
    applicant: opts.applicant,
    render_mode: baseRenderMode,
    interventions: Object.freeze(baseInterventions),
  });
  
  const cf: ArmPlan = Object.freeze({
    arm_id: opts.cfArmId,
    applicant: opts.applicant,
    render_mode: cfRenderMode,
    interventions: Object.freeze(cfInterventions),
  });
  
  const effectiveSeedGroup = opts.seedGroup || contentId({
    purpose: "paired-common-random-numbers",
    applicant_id: opts.applicant.applicant_id,
    base_applicant_content_id: applicantContentId(base.applicant),
  });
  
  const pairId = pairIdForPlan({
    check: opts.check,
    baseArmId: opts.baseArmId,
    cfArmId: opts.cfArmId,
    baseInterventionIds: baseInterventions.map(s => s.intervention_id),
    cfInterventionIds: cfInterventions.map(s => s.intervention_id),
  });
  
  return Object.freeze({
    pair_id: pairId,
    cluster_id: clusterIdFor(opts.applicant),
    seed_group: effectiveSeedGroup,
    check: opts.check,
    family: opts.family,
    relation: opts.relation,
    base,
    cf,
  });
}
