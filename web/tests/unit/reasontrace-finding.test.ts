import { describe, expect, it } from "vitest";
import { summarizeScriptedFinding } from "../../components/reasontrace-finding-summary";

describe("scripted finding wording", () => {
  it("prioritizes a decision mismatch over paired-check status", () => {
    const finding = summarizeScriptedFinding([{ status: "pass" }], "APPROVE", "DENY");
    expect(finding.tone).toBe("fail");
    expect(finding.headline).toContain("differs from policy");
  });

  it("points to the first failed paired check", () => {
    const finding = summarizeScriptedFinding(
      [{ status: "pass" }, { status: "fail" }, { status: "fail" }], "DENY", "DENY",
    );
    expect(finding.tone).toBe("fail");
    expect(finding.targetIndex).toBe(1);
    expect(finding.detail).toContain("2 of 3");
  });

  it("distinguishes an inapplicable approval from a passing denial", () => {
    const approval = summarizeScriptedFinding([{ status: "inapplicable" }], "APPROVE", "APPROVE");
    expect(approval.tone).toBe("neutral");
    expect(approval.headline).toContain("No adverse explanation");
    const denial = summarizeScriptedFinding([{ status: "pass" }], "DENY", "DENY");
    expect(denial.tone).toBe("pass");
  });

  it("does not call missing or unrecognized checks a pass", () => {
    expect(summarizeScriptedFinding([], "DENY", "DENY").tone).toBe("neutral");
    expect(summarizeScriptedFinding([{ status: "pass" }, { status: "error" }], "DENY", "DENY").tone).toBe("neutral");
  });
});
