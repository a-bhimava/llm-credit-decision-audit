import test from "node:test";
import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import { buildApplicationPacket } from "../../../lib/audit/render/packet";
import { renderJson } from "../../../lib/audit/render/json";

test("Render Packet Parity", () => {
  const fixturePath = path.join(__dirname, "../../fixtures/render.json");
  const data = JSON.parse(fs.readFileSync(fixturePath, "utf-8"));
  
  const idsPath = path.join(__dirname, "../../fixtures/ids.json");
  const appData = JSON.parse(fs.readFileSync(idsPath, "utf-8")).applicant;

  const app: any = {
    applicant_id: appData.applicant_id,
    facts: appData.facts,
    presentation: appData.presentation,
    dti: { toString: () => appData.dti ?? data.packet.income.debt_to_income_ratio },
    utilization: { toString: () => appData.utilization ?? data.packet.credit_file.revolving.utilization },
    cltv: { toString: () => appData.cltv ?? "0" }
  };

  const p = buildApplicationPacket(app);
  assert.deepStrictEqual(p, data.packet);
});

test("Render JSON Parity", () => {
  const idsPath = path.join(__dirname, "../../fixtures/ids.json");
  const appData = JSON.parse(fs.readFileSync(idsPath, "utf-8")).applicant;
  const data = JSON.parse(fs.readFileSync(path.join(__dirname, "../../fixtures/render.json"), "utf-8"));

  const app: any = {
    applicant_id: appData.applicant_id,
    facts: appData.facts,
    presentation: appData.presentation,
    dti: { toString: () => appData.dti ?? data.packet.income.debt_to_income_ratio },
    utilization: { toString: () => appData.utilization ?? data.packet.credit_file.revolving.utilization },
    cltv: { toString: () => appData.cltv ?? "0" }
  };

  const str = renderJson(app, "json");
  assert.strictEqual(str, data.json_str_sorted);
  
  const strShuffled = renderJson(app, "json", { json_field_order_seed: 42 });
  assert.strictEqual(strShuffled, data.json_str_shuffled);
});
