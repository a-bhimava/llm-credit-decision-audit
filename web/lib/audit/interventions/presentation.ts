import { Family, InterventionSpec, Layer, Relation } from "../records";
import { contentId } from "../ids";
import { getSignalTemplate, SignalTemplate, RACE_SIGNALS, SEX_SIGNALS } from "./signals";

export type PresentationContrast = Readonly<{
  contrast_id: string;
  family: Family;
  label: string;
  diagnostic: boolean;
  metadata: Record<string, string>;
  base_spec: InterventionSpec;
  cf_spec: InterventionSpec;
}>;

function spec(opts: {
  family: Family;
  name: string;
  layer: Layer;
  targets?: Record<string, any>;
  options?: Record<string, any>;
  targetField?: string;
  diagnostic?: boolean;
}): InterventionSpec {
  return Object.freeze({
    intervention_id: contentId(opts.options ? {
      family: opts.family,
      name: opts.name,
      options: opts.options,
    } : {
      family: opts.family,
      name: opts.name,
      targets: opts.targets,
    }),
    family: opts.family,
    name: opts.name,
    layer: opts.layer,
    target_field: opts.targetField === undefined ? null : opts.targetField,
    direction: "set",
    expected_relation: "INVARIANT" as Relation,
    params: Object.freeze(opts.options ? { options: Object.freeze({ ...opts.options }) } : { targets: Object.freeze({ ...opts.targets }) }),
  });
}

function contrast(
  name: string,
  label: string,
  family: Family,
  base: InterventionSpec,
  cf: InterventionSpec,
  opts: { metadata?: Record<string, string>, diagnostic?: boolean } = {}
): PresentationContrast {
  return Object.freeze({
    contrast_id: contentId({
      family,
      name,
      base_id: base.intervention_id,
      cf_id: cf.intervention_id,
    }),
    family,
    label,
    diagnostic: opts.diagnostic || false,
    metadata: Object.freeze({ ...(opts.metadata || {}) }),
    base_spec: base,
    cf_spec: cf,
  });
}

function signalTargets(template: SignalTemplate): Record<string, any> {
  return {
    applicant_name: `${template.first_name} ${template.surname}`,
    pronouns: template.pronouns,
    graduation_year: template.graduation_year,
    demographic_tags: {
      age_band_signal: template.age_band_signal,
      race_ethnicity_signal: template.race_ethnicity_signal,
      sex_signal: template.sex_signal,
      source: "census-2010+ssa-national:sha256:40c51a7aa5023712447dcf65b047e9cc0ec42d66cd1624bcadfb087fd9a4619f",
      synthetic: true,
    },
  };
}

function demographicSignalSpec(template: SignalTemplate, label: string): InterventionSpec {
  return spec({
    family: "DEMOGRAPHIC",
    name: `demographic.${label}`,
    layer: "presentation",
    targets: signalTargets(template),
  });
}

export function recordedSexContrast(
  templateIndex: number,
  raceEthnicity = "white_non_hispanic",
  cohort = "1982_1991"
): PresentationContrast {
  const female = getSignalTemplate(templateIndex, raceEthnicity as any, "female", cohort as any);
  const male = getSignalTemplate(templateIndex, raceEthnicity as any, "male", cohort as any);
  return contrast(
    "recorded_sex",
    "female versus male first-name and pronoun signal",
    "DEMOGRAPHIC",
    demographicSignalSpec(female, "sex.female"),
    demographicSignalSpec(male, "sex.male"),
    { metadata: { signal_dimension: "recorded_sex" } }
  );
}

export function raceEthnicityContrasts(templateIndex: number): readonly PresentationContrast[] {
  const reference = getSignalTemplate(templateIndex, "white_non_hispanic", "female", "1982_1991");
  const base = demographicSignalSpec(reference, "race.white_non_hispanic");
  const contrasts: PresentationContrast[] = [];
  
  for (let i = 1; i < RACE_SIGNALS.length; i++) {
    const race = RACE_SIGNALS[i];
    const changed = getSignalTemplate(templateIndex, race, "female", "1982_1991");
    const merged = { ...changed, first_name: reference.first_name };
    const cf = demographicSignalSpec(merged, `race.${race}`);
    contrasts.push(
      contrast(
        `race.${race}`,
        `surname signal: white_non_hispanic versus ${race}`,
        "DEMOGRAPHIC",
        base,
        cf,
        { metadata: { signal_dimension: "race_ethnicity", comparison: race } }
      )
    );
  }
  return Object.freeze(contrasts);
}

export function ageContrasts(templateIndex: number): readonly PresentationContrast[] {
  const middle = getSignalTemplate(templateIndex, "white_non_hispanic", "female", "1982_1991");
  const base = demographicSignalSpec(middle, "age.1982_1991");
  const contrasts: PresentationContrast[] = [];
  
  const cohorts = ["1952_1961", "1992_2001"];
  for (const cohort of cohorts) {
    const changed = getSignalTemplate(templateIndex, "white_non_hispanic", "female", cohort as any);
    const cf = demographicSignalSpec(changed, `age.${cohort}`);
    contrasts.push(
      contrast(
        `age.${cohort}`,
        `middle versus ${cohort} age-associated signal`,
        "DEMOGRAPHIC",
        base,
        cf,
        { metadata: { signal_dimension: "age", comparison: cohort } }
      )
    );
  }
  return Object.freeze(contrasts);
}

export function intersectionalContrasts(templateIndex: number): readonly PresentationContrast[] {
  const reference = getSignalTemplate(templateIndex, "white_non_hispanic", "female", "1982_1991");
  const base = demographicSignalSpec(reference, "intersection.white_non_hispanic.female");
  const contrasts: PresentationContrast[] = [];
  
  for (const race of RACE_SIGNALS) {
    for (const sex of SEX_SIGNALS) {
      if (race === "white_non_hispanic" && sex === "female") continue;
      const changed = getSignalTemplate(templateIndex, race, sex, "1982_1991");
      const cf = demographicSignalSpec(changed, `intersection.${race}.${sex}`);
      contrasts.push(
        contrast(
          `intersection.${race}.${sex}`,
          `diagnostic intersectional signal: ${race}/${sex}`,
          "DEMOGRAPHIC",
          base,
          cf,
          { 
            diagnostic: true,
            metadata: { 
              signal_dimension: "race_x_recorded_sex", 
              race_ethnicity: race,
              recorded_sex: sex
            } 
          }
        )
      );
    }
  }
  return Object.freeze(contrasts);
}

const PARAPHRASE_A = "Applicant confirms the submitted information is complete and accurate.";
const PARAPHRASE_B = "The applicant attests that all information provided is accurate and complete.";

export function paraphraseContrast(): PresentationContrast {
  const base = spec({
    family: "INVARIANCE",
    name: "paraphrase.version_a",
    layer: "presentation",
    targets: { free_text_notes: [PARAPHRASE_A] },
    targetField: "free_text_notes",
  });
  const cf = spec({
    family: "INVARIANCE",
    name: "paraphrase.version_b",
    layer: "presentation",
    targets: { free_text_notes: [PARAPHRASE_B] },
    targetField: "free_text_notes",
  });
  return contrast("paraphrase", "semantically equivalent note", "INVARIANCE", base, cf);
}

export function authorityContrast(): PresentationContrast {
  const low = spec({
    family: "AUTHORITY",
    name: "authority.low",
    layer: "presentation",
    targets: { employer_name: "Neighborhood Retail Services", employer_prestige_tier: 5, referral_note: null, school: "Regional Community College" },
  });
  const high = spec({
    family: "AUTHORITY",
    name: "authority.high",
    layer: "presentation",
    targets: { employer_name: "Meridian Research Institute", employer_prestige_tier: 1, referral_note: "Executive referral: Office of the Chair.", school: "Northbridge Institute of Technology" },
  });
  return contrast("authority", "low versus high authority bundle", "AUTHORITY", low, high);
}

export function statementOrderContrast(): PresentationContrast {
  const lines = [
    { day: 2, description: "Direct deposit", amount_cents: 245000 },
    { day: 4, description: "Rent payment", amount_cents: -135000 },
    { day: 8, description: "Utility payment", amount_cents: -18400 },
    { day: 14, description: "Grocery purchase", amount_cents: -12650 },
    { day: 18, description: "Direct deposit", amount_cents: 245000 },
    { day: 25, description: "Insurance payment", amount_cents: -21300 },
  ];
  const base = spec({
    family: "INVARIANCE",
    name: "statement_order.canonical",
    layer: "presentation",
    targets: { bank_statement_lines: lines, line_order_seed: 0 },
  });
  const cf = spec({
    family: "INVARIANCE",
    name: "statement_order.permuted",
    layer: "presentation",
    targets: { bank_statement_lines: lines, line_order_seed: 611 },
  });
  return contrast("statement_order", "statement line order", "INVARIANCE", base, cf);
}

export function fieldOrderContrast(): PresentationContrast {
  const base = spec({
    family: "INVARIANCE", 
    name: "field_order.canonical",
    layer: "render",
    options: { json_field_order_seed: null },
    targetField: "json_field_order_seed",
  });
  const cf = spec({
    family: "INVARIANCE", 
    name: "field_order.permuted",
    layer: "render",
    options: { json_field_order_seed: 947 },
    targetField: "json_field_order_seed",
  });
  return contrast("field_order", "JSON field order", "INVARIANCE", base, cf);
}
