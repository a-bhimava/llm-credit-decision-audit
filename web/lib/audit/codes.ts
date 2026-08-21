import { policy } from "./policy";

export const FORM_C1_PHRASES: Record<string, string> = {
  INSUFFICIENT_INCOME: "Income insufficient for amount of credit requested",
  EXCESSIVE_OBLIGATIONS_DTI: "Excessive obligations in relation to income",
  INSUFFICIENT_CREDIT_HISTORY: "Limited credit experience",
  DELINQUENT_OBLIGATIONS: "Delinquent past or present credit obligations with others",
  DEROGATORY_PUBLIC_RECORD: "Collection action or judgment",
  BANKRUPTCY: "Bankruptcy",
  TOO_MANY_INQUIRIES: "Number of recent inquiries on credit bureau report",
  INSUFFICIENT_EMPLOYMENT_HISTORY: "Length of employment",
  TEMPORARY_OR_IRREGULAR_EMPLOYMENT: "Temporary or irregular employment",
  UNVERIFIABLE_INCOME: "Unable to verify income",
  COLLATERAL_VALUE_INSUFFICIENT: "Value or type of collateral not sufficient",
  INCOMPLETE_APPLICATION: "Credit application incomplete",
  OTHER_UNMAPPED: "Other, specify",
};

export const ZERO_API_CALL_CODES = new Set([
  "NON_SPECIFIC_INTERNAL_POLICY",
  "PROHIBITED_BASIS_ADJACENT",
  "OUT_OF_SCHEMA_FACTOR",
]);

export type CodeMeta = Readonly<{
  code: string;
  repairable: boolean;
  severity: number | null;
  target_fields: readonly string[];
  repair_kind: string | null;
  form_c1_phrase: string | null;
  zero_api_call: boolean;
  note: string;
}>;

function buildCodeMeta(): Record<string, CodeMeta> {
  const result: Record<string, CodeMeta> = {};
  
  // Collect all known codes from policy rules + static ones
  const allCodes = new Set([
    ...policy.rules.map(r => r.reason_code),
    ...Object.keys(FORM_C1_PHRASES),
    ...ZERO_API_CALL_CODES,
    "OUT_OF_POLICY_FACTOR"
  ]);

  for (const code of allCodes) {
    const rules = policy.rules.filter(r => r.reason_code === code);
    if (rules.length > 0) {
      const kinds = new Set(rules.map(r => r.repair.kind));
      if (kinds.size !== 1) throw new Error("Rules disagree on repair kind");
      
      const fields = new Set<string>();
      for (const r of rules) {
        for (const f of r.repair.fields) fields.add(f);
      }
      
      result[code] = Object.freeze({
        code,
        repairable: true,
        severity: Math.max(...rules.map(r => r.severity)),
        target_fields: Object.freeze(Array.from(fields)),
        repair_kind: Array.from(kinds)[0]!,
        form_c1_phrase: FORM_C1_PHRASES[code] || null,
        zero_api_call: ZERO_API_CALL_CODES.has(code),
        note: `Rule-driven: ${rules.map(r => r.rule_id).join(", ")}.`,
      });
    } else {
      result[code] = Object.freeze({
        code,
        repairable: false,
        severity: null,
        target_fields: Object.freeze([]),
        repair_kind: null,
        form_c1_phrase: FORM_C1_PHRASES[code] || null,
        zero_api_call: ZERO_API_CALL_CODES.has(code),
        note: `No rules for ${code}`, // simplified
      });
    }
  }
  return result;
}

let cached: Record<string, CodeMeta> | null = null;
export function getCodeMeta(): Record<string, CodeMeta> {
  if (!cached) cached = buildCodeMeta();
  return cached;
}
