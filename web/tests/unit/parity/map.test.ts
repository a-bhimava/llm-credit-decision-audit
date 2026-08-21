import test from "node:test";
import assert from "node:assert";
import { mapReason } from "../../../lib/audit/map";

test("Map Reason Parity", () => {
  const c1 = mapReason("Income insufficient for amount of credit requested");
  assert.strictEqual(c1[0].code, "INSUFFICIENT_INCOME");
  assert.strictEqual(c1[0].method, "lexicon");
  
  const c2 = mapReason("Income insufficient for amount of credit requested and bankruptcy");
  assert.strictEqual(c2.length, 2);
  assert.strictEqual(c2[0].code, "INSUFFICIENT_INCOME");
  assert.strictEqual(c2[1].code, "BANKRUPTCY");
  
  const c3 = mapReason("debt obligations exceed income amount requested");
  assert.strictEqual(c3[0].code, "EXCESSIVE_OBLIGATIONS_DTI");
  assert.strictEqual(c3[0].method, "embedding"); 
  assert.ok(Math.abs(c3[0].confidence - 0.522976) < 1e-3);
  
  const c4 = mapReason("just completely bad file");
  assert.strictEqual(c4[0].code, "OTHER_UNMAPPED");
  
  const c5 = mapReason("the applicant's income is insufficient and their annual income does not meet the minimum");
  assert.strictEqual(c5.length, 1);
  assert.strictEqual(c5[0].code, "INSUFFICIENT_INCOME");
  assert.strictEqual(c5[0].split, true);
});
