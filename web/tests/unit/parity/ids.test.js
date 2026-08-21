"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const node_test_1 = __importDefault(require("node:test"));
const node_assert_1 = __importDefault(require("node:assert"));
const node_fs_1 = __importDefault(require("node:fs"));
const node_path_1 = __importDefault(require("node:path"));
const ids_1 = require("../../../lib/audit/ids");
(0, node_test_1.default)("IDs Parity", () => {
    const fixturePath = node_path_1.default.join(__dirname, "../../fixtures/ids.json");
    const data = JSON.parse(node_fs_1.default.readFileSync(fixturePath, "utf-8"));
    const app = data.applicant;
    // Test canonical_json
    node_assert_1.default.strictEqual((0, ids_1.canonicalJson)(app.facts), data.canonical_facts);
    node_assert_1.default.strictEqual((0, ids_1.canonicalJson)(app.presentation), data.canonical_presentation);
    // Test content ID
    node_assert_1.default.strictEqual((0, ids_1.applicantContentId)(app), data.applicant_content_id);
    // Test episode_input_hash
    const hash = (0, ids_1.episodeInputHash)(app, "mock text", "ref", "json");
    node_assert_1.default.strictEqual(hash, data.episode_input_hash);
    // Test cluster_id
    node_assert_1.default.strictEqual((0, ids_1.clusterIdFor)(app), data.cluster_id);
});
