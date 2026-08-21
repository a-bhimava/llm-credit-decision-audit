import test from "node:test";
import assert from "node:assert";
import { Ratio, assertCents } from "../../lib/audit/money";

test("Ratio arithmetic", () => {
  const r1 = Ratio.fromNumber(0.43555);
  assert.strictEqual(r1.toNumber(), 0.4356);
  assert.strictEqual(r1.toJSON(), 0.4356);
  assert.strictEqual(r1.toString(), "0.4356");

  const r2 = Ratio.fromFraction(10, 3);
  assert.strictEqual(r2.toNumber(), 3.3333);

  const r3 = Ratio.fromPercent(43.5);
  assert.strictEqual(r3.toNumber(), 0.4350);

  assert.ok(r2.gt(r1));
  assert.ok(r1.lt(r2));
});

test("assertCents", () => {
  assert.strictEqual(assertCents(100), 100);
  assert.throws(() => assertCents(100.5), TypeError);
});
