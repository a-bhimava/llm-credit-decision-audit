import test from "node:test";
import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import { canonicalJson, applicantContentId, episodeInputHash, clusterIdFor } from "../../../lib/audit/ids";

test("IDs Parity", () => {
  const fixturePath = path.join(__dirname, "../../fixtures/ids.json");
  const data = JSON.parse(fs.readFileSync(fixturePath, "utf-8"));

  const app = data.applicant;
  
  // Test canonical_json
  assert.strictEqual(canonicalJson(app.facts), data.canonical_facts);
  assert.strictEqual(canonicalJson(app.presentation), data.canonical_presentation);
  
  // Test content ID
  assert.strictEqual(applicantContentId(app), data.applicant_content_id);
  
  // Test episode_input_hash
  const hash = episodeInputHash(app, "mock text", "ref", "json");
  assert.strictEqual(hash, data.episode_input_hash);
  
  // Test cluster_id
  assert.strictEqual(clusterIdFor(app), data.cluster_id);
});
