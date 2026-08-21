import { Applicant, DecisionOutcome, Decision, StatedReason } from "./records";
import { Ratio } from "./money";
import { policy } from "./policy";

export type Accessor = {
  kind: "primitive" | "property" | "derived";
  field?: string;
  name?: string;
  params?: Record<string, any>;
};

export type RuleEvaluation = Readonly<{
  rule_id: string;
  reason_code: string;
  anchor: string;
  severity: number;
  predicate: string;
  breached: boolean;
  observed: number | string | boolean;
  observed_display: string;
  threshold: number | string | boolean;
  threshold_display: string | undefined;
  operator: string;
  slack: number;
  margin: number;
  margin_unit: number;
  margin_kind: string;
  boundary_stratify: boolean;
  repair: any;
}>;

export type GroundTruthDecision = Readonly<{
  policy_version: string;
  "sha256": string;
  outcome: DecisionOutcome;
  evaluations: readonly RuleEvaluation[];
  counteroffer_available: boolean;
}>;

function readAccessor(applicant: Applicant, acc: any): any {
  if (acc.kind === "primitive" || acc.kind === "property") {
    return (applicant.facts as any)[acc.field!] ?? (applicant as any)[acc.field!];
  }
  if (acc.kind === "derived") {
    if (acc.name === "loan_to_income") {
      if (applicant.facts.annual_income_cents <= 0) return Ratio.fromNumber(1000);
      return Ratio.fromFraction(applicant.facts.loan_amount_cents, applicant.facts.annual_income_cents);
    }
    if (acc.name === "delinq_minor_count_24m") return applicant.facts.delinq_30d_24m + applicant.facts.delinq_60d_24m;
    if (acc.name === "months_since_public_record") {
      const records = applicant.facts.public_records.filter(r => acc.params.kinds.includes(r.kind) && r.amount_cents >= parseInt(acc.params.min_amount_cents, 10));
      if (records.length === 0) return 1200;
      return Math.min(...records.map(r => r.months_ago));
    }
  }
  throw new Error(`unhandled accessor: ${JSON.stringify(acc)}`);
}

function parseRatio(str: string): Ratio {
  return Ratio.fromFraction(Math.round(parseFloat(str) * 10000), 10000);
}

export function evaluateRule(applicant: Applicant, rule: any): RuleEvaluation {
  const raw = readAccessor(applicant, rule.accessor);
  
  let observed: number;
  let threshold: number;
  let operator: string;
  let observedDisplay: string;
  
  if (rule.predicate === "flag_true") {
    observed = raw ? 1 : 0;
    threshold = 1;
    operator = ">=";
    observedDisplay = raw ? "yes" : "no";
  } else if (rule.predicate === "enum_allowed") {
    observed = rule.allowed.includes(String(raw)) ? 1 : 0;
    threshold = 1;
    operator = ">=";
    observedDisplay = String(raw);
  } else if (rule.predicate === "numeric_min" || rule.predicate === "numeric_max") {
    operator = rule.predicate === "numeric_min" ? ">=" : "<=";
    
    if (raw instanceof Ratio) {
      observed = raw.toNumber();
    } else {
      observed = Number(raw);
    }

    if (rule.value_kind === "ratio") {
      threshold = parseRatio(rule.threshold).toNumber();
    } else {
      threshold = Number(rule.threshold);
    }
    
    if (rule.margin_kind === "continuous" && (rule.accessor.kind === "property" || rule.accessor.kind === "derived")) {
      observedDisplay = (observed * 100).toFixed(4).replace(/\.?0+$/, "") + "%"; // match normalize():f
    } else if (rule.accessor.field && rule.accessor.field.endsWith("_cents")) {
      observedDisplay = (observed / 100).toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2});
      observedDisplay = observedDisplay.replace(/\.00$/, "");
      observedDisplay = "$" + observedDisplay;
    } else {
      observedDisplay = String(observed);
    }
  } else {
    throw new Error("Unhandled predicate");
  }
  
  const sign = operator === ">=" ? 1 : -1;
  let slack = sign * (observed - threshold);
  if (Math.abs(slack) < 1e-10) slack = 0;
  
  const breached = slack < 0;
  let margin = slack / Number(rule.margin_unit);
  if (Math.abs(margin) < 1e-10) margin = 0;
  margin = Math.round(margin * 10000) / 10000;

  return {
    rule_id: rule.rule_id,
    reason_code: rule.reason_code,
    anchor: rule.anchor,
    severity: rule.severity,
    predicate: rule.predicate,
    breached,
    observed,
    observed_display: observedDisplay,
    threshold,
    threshold_display: rule.display_value,
    operator,
    slack,
    margin,
    margin_unit: Number(rule.margin_unit),
    margin_kind: rule.margin_kind,
    boundary_stratify: rule.boundary_stratify,
    repair: rule.repair,
  };
}

export function evaluate(applicant: Applicant): GroundTruthDecision {
  const evaluations = policy.rules.map(rule => evaluateRule(applicant, rule));
  const anyBreach = evaluations.some(e => e.breached);
  
  const breachedRules = evaluations.filter(e => e.breached);
  let counteroffer = false;
  if (breachedRules.length > 0) {
    const amountDriven = ["max_loan_to_income", "max_loan_amount"];
    counteroffer = breachedRules.every(e => amountDriven.includes(e.rule_id));
  }
  
  return {
    policy_version: policy.version,
    "sha256": "sha256",
    outcome: anyBreach ? "DENY" : "APPROVE",
    evaluations,
    counteroffer_available: counteroffer,
  };
}
