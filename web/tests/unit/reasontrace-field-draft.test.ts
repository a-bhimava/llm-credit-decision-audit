import { describe, expect, it } from "vitest";
import { formatFieldDraft, parseFieldDraft } from "../../lib/reasontrace/field-draft";

describe("reviewed numeric drafts", () => {
  it("keeps incomplete or malformed money separate from a real zero", () => {
    expect(parseFieldDraft("annual_income_cents", "")).toBeNull();
    expect(parseFieldDraft("annual_income_cents", "  ")).toBeNull();
    expect(parseFieldDraft("annual_income_cents", "0")).toBe(0);
    expect(parseFieldDraft("annual_income_cents", "60000.25")).toBe(6_000_025);
    expect(parseFieldDraft("annual_income_cents", "60000.")).toBeNull();
    expect(parseFieldDraft("annual_income_cents", "60000.255")).toBeNull();
    expect(parseFieldDraft("annual_income_cents", "6e4")).toBeNull();
    expect(parseFieldDraft("annual_income_cents", "600000.01")).toBeNull();
  });

  it("requires an in-range whole-number credit score", () => {
    expect(parseFieldDraft("credit_score", "620")).toBe(620);
    expect(parseFieldDraft("credit_score", "620.5")).toBeNull();
    expect(parseFieldDraft("credit_score", "299")).toBeNull();
    expect(parseFieldDraft("credit_score", "851")).toBeNull();
    expect(parseFieldDraft("credit_score", "")).toBeNull();
  });

  it("formats saved cents without losing nonzero decimal places", () => {
    expect(formatFieldDraft("annual_income_cents", 6_000_000)).toBe("60000");
    expect(formatFieldDraft("monthly_debt_cents", 60_050)).toBe("600.50");
    expect(parseFieldDraft("monthly_debt_cents", formatFieldDraft("monthly_debt_cents", 60_050))).toBe(60_050);
    expect(formatFieldDraft("credit_score", 635)).toBe("635");
  });
});
