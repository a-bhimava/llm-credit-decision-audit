/**
 * Public-runtime contracts for a one-applicant diagnostic audit.
 *
 * The Python implementation remains the executable conformance reference while the
 * TypeScript runner is ported family by family. These records deliberately accept only
 * fictional financial facts: there is no name, address, free text, identifier, upload,
 * demographic field, or account number anywhere in the public request shape.
 */

export const AUDIT_FAMILIES = [
  "policy_adherence",
  "monotonicity",
  "invariance",
  "serialization",
  "counterfactual_bias",
  "reason_validity",
] as const;

export type AuditFamily = (typeof AUDIT_FAMILIES)[number];

export const EMPLOYMENT_STATUSES = [
  "FULL_TIME",
  "PART_TIME",
  "SELF_EMPLOYED",
  "CONTRACT",
  "RETIRED",
  "UNEMPLOYED",
] as const;

export type EmploymentStatus = (typeof EMPLOYMENT_STATUSES)[number];

export const PUBLIC_RECORD_KINDS = ["NONE", "COLLECTION", "TAX_LIEN", "JUDGMENT", "BANKRUPTCY_CH7", "BANKRUPTCY_CH13"] as const;
export type PublicRecordKind = (typeof PUBLIC_RECORD_KINDS)[number];

export type FinancialFacts = Readonly<{
  annualIncomeCents: number;
  monthlyDebtCents: number;
  loanAmountCents: number;
  loanTermMonths: number;
  creditScore: number;
  revolvingBalanceCents: number;
  revolvingLimitCents: number;
  delinq30d24m: number;
  delinq60d24m: number;
  delinq90p24m: number;
  publicRecordKind: PublicRecordKind;
  publicRecordMonthsAgo: number;
  inquiries6m: number;
  employmentMonths: number;
  employmentStatus: EmploymentStatus;
  incomeDocumented: boolean;
}>;

export type AuditIntake = Readonly<{
  facts: FinancialFacts;
  /** User-facing acknowledgement that the facts are fictional. */
  fictionalAcknowledged: true;
}>;

export type AuditConfiguration = Readonly<{
  id: "baseline" | "platform";
  label: string;
  description: string;
  toolsEnabled: boolean;
}>;

export const AUDIT_CONFIGURATIONS: readonly AuditConfiguration[] = [
  {
    id: "baseline",
    label: "Structured baseline",
    description: "The policy and application are supplied together; the model submits one structured decision without audit tools.",
    toolsEnabled: false,
  },
  {
    id: "platform",
    label: "Tool-guided platform",
    description: "The same policy is supplied with auditable tools and required-tool checks before a decision is accepted.",
    toolsEnabled: true,
  },
] as const;

export type AuditStatus =
  | "queued"
  | "planning"
  | "running"
  | "complete"
  | "cancelled"
  | "failed"
  | "budget_exhausted";

export type AuditPreflight = Readonly<{
  kTrials: 5;
  families: readonly AuditFamily[];
  plannedEpisodesLower: number;
  plannedEpisodesUpper: number;
  estimatedUsdUpper: number;
  perConfigurationUsdCap: number;
  jobUsdCap: number;
  dailyUsdCap: number;
  pricingVersion: string;
}>;

export type AuditProgress = Readonly<{
  status: AuditStatus;
  completedEpisodes: number;
  plannedEpisodesUpper: number;
  currentConfiguration?: AuditConfiguration["id"];
  spentUsd: number;
  message: string;
}>;

export type AuditJobView = Readonly<{
  id: string;
  expiresAt: string;
  preflight: AuditPreflight;
  progress: AuditProgress;
  workflowRunId?: string;
}>;
