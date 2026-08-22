export type AuditFamily = "REASON_REPAIR" | "MONOTONE" | "INVARIANCE" | "SERIALIZATION" | "POLICY_ADHERENCE" | "DEMOGRAPHIC" | "AUTHORITY";
export type Family = AuditFamily;
export type PublicRecordKind = "BANKRUPTCY_CH7" | "BANKRUPTCY_CH13" | "TAX_LIEN" | "JUDGMENT" | "COLLECTION";
export type EmploymentStatus = "FULL_TIME" | "PART_TIME" | "SELF_EMPLOYED" | "UNEMPLOYED" | "RETIRED" | "CONTRACT";

export type PublicRecord = Readonly<{
  kind: PublicRecordKind;
  months_ago: number;
  amount_cents: number;
}>;

export type FinancialFacts = Readonly<{
  annual_income_cents: number;
  monthly_debt_cents: number;
  loan_amount_cents: number;
  property_value_cents: number;
  loan_term_months: number;
  
  credit_score: number;
  open_tradelines: number;
  revolving_balance_cents: number;
  revolving_limit_cents: number;
  
  delinq_30d_24m: number;
  delinq_60d_24m: number;
  delinq_90p_24m: number;
  public_records: readonly PublicRecord[];
  
  oldest_tradeline_months: number;
  inquiries_6m: number;
  
  employment_months: number;
  employment_status: EmploymentStatus;
  income_documented: boolean;
}>;

export const AUDIT_FAMILIES = ["POLICY_ADHERENCE", "MONOTONE", "INVARIANCE", "SERIALIZATION", "DEMOGRAPHIC", "AUTHORITY"] as const;

export type AuditPreflight = {
  kTrials: number;
  families: readonly AuditFamily[];
  plannedEpisodesLower: number;
  plannedEpisodesUpper: number;
  estimatedUsdUpper: number;
  perConfigurationUsdCap: number;
  jobUsdCap: number;
  dailyUsdCap: number;
  pricingVersion: string;
};

export type AuditIntake = {
  facts: FinancialFacts;
  fictionalAcknowledged: boolean;
};

export type AuditJobView = {
  id: string;
  expiresAt: string;
  preflight: AuditPreflight;
  progress: AuditProgress;
  workflowRunId?: string;
};

export type AuditProgress = {
  status: string;
  completedEpisodes: number | any[];
  plannedEpisodesUpper: number;
  spentUsd: number;
  message: string;
};
