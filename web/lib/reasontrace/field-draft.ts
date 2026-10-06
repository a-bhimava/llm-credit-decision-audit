import { fieldDefinitions, reviewFieldRanges, type FieldId } from "./demo";

export function formatFieldDraft(id: FieldId, value: number): string {
  if (fieldDefinitions[id].unit === "score") return String(value);
  const dollars = Math.floor(value / 100);
  const cents = value % 100;
  return cents ? `${dollars}.${String(cents).padStart(2, "0")}` : String(dollars);
}

/** Empty, partial, fractional-score and out-of-range drafts never become zero by coercion. */
export function parseFieldDraft(id: FieldId, raw: string): number | null {
  const text = raw.trim();
  const money = fieldDefinitions[id].unit === "money";
  const match = money ? /^(\d+)(?:\.(\d{1,2}))?$/.exec(text) : /^(\d+)$/.exec(text);
  if (!match) return null;
  const value = money
    ? Number(match[1]) * 100 + Number((match[2] ?? "").padEnd(2, "0"))
    : Number(match[1]);
  const [minimum, maximum] = reviewFieldRanges[id];
  return Number.isSafeInteger(value) && value >= minimum && value <= maximum ? value : null;
}
