import { demographicSignals } from "./signals_data";

export type RaceSignal = "white_non_hispanic" | "black_non_hispanic" | "asian_nhpi" | "hispanic_latino";
export type SexSignal = "female" | "male";
export type CohortSignal = "1952_1961" | "1982_1991" | "1992_2001";

export const RACE_SIGNALS: readonly RaceSignal[] = ["white_non_hispanic", "black_non_hispanic", "asian_nhpi", "hispanic_latino"];
export const SEX_SIGNALS: readonly SexSignal[] = ["female", "male"];
export const COHORT_SIGNALS: readonly CohortSignal[] = ["1952_1961", "1982_1991", "1992_2001"];

export type SignalCatalog = Readonly<{
  schema_name: string;
  catalog_version: string;
  framing: string;
  sources: any;
  surnames: any;
  first_names: any;
  pronouns: any;
  sha256: string;
}>;

export type SignalTemplate = Readonly<{
  template_index: number;
  first_name: string;
  surname: string;
  pronouns: string;
  graduation_year: number;
  race_ethnicity_signal: RaceSignal;
  sex_signal: SexSignal;
  age_band_signal: string;
  cohort: CohortSignal;
  applicant_name: string;
}>;

let cachedCatalog: SignalCatalog | null = null;

export function loadSignalCatalog(): SignalCatalog {
  if (cachedCatalog) return cachedCatalog;
  const raw: any = demographicSignals;

  if (raw.schema !== "credit-audit/demographic-signals@1") {
    throw new Error("unsupported demographic signal catalog schema");
  }

  cachedCatalog = Object.freeze({
    schema_name: raw.schema,
    catalog_version: raw.catalog_version,
    framing: raw.framing,
    sources: Object.freeze({ ...raw.sources }),
    surnames: Object.freeze({ ...raw.surnames }),
    first_names: Object.freeze({ ...raw.first_names }),
    pronouns: Object.freeze({ ...raw.pronouns }),
    sha256: "static-bundle-hash-ignored",
  });
  return cachedCatalog;
}

export function getSignalTemplate(
  index: number,
  raceEthnicity: RaceSignal,
  sex: SexSignal,
  cohort: CohortSignal
): SignalTemplate {
  const catalog = loadSignalCatalog();
  const slot = index % 8;
  if (!catalog.first_names) throw new Error("no first_names on catalog");
  if (!catalog.first_names[cohort]) throw new Error("no cohort " + cohort + " in first_names");

  const cohortData = catalog.first_names[cohort];
  const firstNameRow = cohortData[sex][slot];
  const surnameRow = catalog.surnames[raceEthnicity][slot];

  return Object.freeze({
    template_index: slot,
    first_name: firstNameRow.name,
    surname: surnameRow.name,
    pronouns: catalog.pronouns[sex],
    graduation_year: cohortData.graduation_year,
    race_ethnicity_signal: raceEthnicity,
    sex_signal: sex,
    age_band_signal: cohortData.age_band_2026,
    cohort,
    applicant_name: `${firstNameRow.name} ${surnameRow.name}`,
  });
}
