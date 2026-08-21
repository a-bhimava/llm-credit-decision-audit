import test from "node:test";
import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import { evaluate } from "../../../lib/audit/oracle";

test("Oracle Parity", () => {
  const fixturePath = path.join(__dirname, "../../fixtures/oracle.json");
  const data = JSON.parse(fs.readFileSync(fixturePath, "utf-8"));
  
  const idsPath = path.join(__dirname, "../../fixtures/ids.json");
  const appData = JSON.parse(fs.readFileSync(idsPath, "utf-8")).applicant;
  
  const app: any = {
    applicant_id: appData.applicant_id,
    facts: appData.facts,
    presentation: appData.presentation,
    dti: { toString: () => appData.dti ?? "0.1380", toNumber: () => 0.138 },
    utilization: { toString: () => appData.utilization ?? "0.4218", toNumber: () => 0.4218 },
    cltv: { toString: () => appData.cltv ?? "0", toNumber: () => 0 }
  };

  const decision = evaluate(app);
  
  assert.strictEqual(decision.outcome, data.outcome);
  assert.strictEqual(decision.counteroffer_available, data.counteroffer_available);
  
  for (let i = 0; i < decision.evaluations.length; i++) {
    const e = decision.evaluations[i];
    const d = data.evaluations[i];
    
    assert.strictEqual(e.rule_id, d.rule_id);
    assert.strictEqual(e.breached, d.breached);
    assert.strictEqual(e.observed_display, d.observed_display);
    
    // Slack/margin parity check (tolerate small float math differences up to 4 decimals)
    assert.ok(Math.abs(e.margin - d.margin) < 1e-4, `Margin mismatch on ${e.rule_id}: ${e.margin} vs ${d.margin}`);
    assert.ok(Math.abs(e.slack - d.slack) < 1e-4, `Slack mismatch on ${e.rule_id}: ${e.slack} vs ${d.slack}`);
  }
});
