import { displayValue, fieldDefinitions, type FieldId } from "./demo";

export type FactChange = { field: string; before: string; after: string };

export function pairedApprovalRates(observed: Record<string, unknown>): {
  base: number; changed: number; matchedTrials: number;
} | null {
  const base = observed.base_approve_rate;
  const changed = observed.cf_approve_rate;
  const matchedTrials = observed.matched_trials;
  if (typeof base !== "number" || !Number.isFinite(base) || base < 0 || base > 1 ||
    typeof changed !== "number" || !Number.isFinite(changed) || changed < 0 || changed > 1 ||
    !Number.isSafeInteger(matchedTrials) || Number(matchedTrials) < 1) return null;
  return { base, changed, matchedTrials: Number(matchedTrials) };
}

export function formatFactChange(change: FactChange): string {
  const label = change.field.replaceAll("_", " ");
  if (!(change.field in fieldDefinitions)) return `${label}: ${change.before} → ${change.after}`;
  const before = Number(change.before);
  const after = Number(change.after);
  if (!Number.isSafeInteger(before) || !Number.isSafeInteger(after)) {
    return `${label}: ${change.before} → ${change.after}`;
  }
  const id = change.field as FieldId;
  return `${fieldDefinitions[id].label}: ${displayValue(id, before)} → ${displayValue(id, after)}`;
}
