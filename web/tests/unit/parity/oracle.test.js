"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const node_test_1 = __importDefault(require("node:test"));
const node_assert_1 = __importDefault(require("node:assert"));
const node_fs_1 = __importDefault(require("node:fs"));
const node_path_1 = __importDefault(require("node:path"));
const oracle_1 = require("../../../lib/audit/oracle");
(0, node_test_1.default)("Oracle Parity", () => {
    const fixturePath = node_path_1.default.join(__dirname, "../../fixtures/oracle.json");
    const data = JSON.parse(node_fs_1.default.readFileSync(fixturePath, "utf-8"));
    const idsPath = node_path_1.default.join(__dirname, "../../fixtures/ids.json");
    const appData = JSON.parse(node_fs_1.default.readFileSync(idsPath, "utf-8")).applicant;
    const app = {
        applicant_id: appData.applicant_id,
        facts: appData.facts,
        presentation: appData.presentation,
        dti: { toString: () => appData.dti ?? "0.1380", toNumber: () => 0.138 },
        utilization: { toString: () => appData.utilization ?? "0.4218", toNumber: () => 0.4218 },
        cltv: { toString: () => appData.cltv ?? "0", toNumber: () => 0 }
    };
    const decision = (0, oracle_1.evaluate)(app);
    node_assert_1.default.strictEqual(decision.outcome, data.outcome);
    node_assert_1.default.strictEqual(decision.counteroffer_available, data.counteroffer_available);
    for (let i = 0; i < decision.evaluations.length; i++) {
        const e = decision.evaluations[i];
        const d = data.evaluations[i];
        node_assert_1.default.strictEqual(e.rule_id, d.rule_id);
        node_assert_1.default.strictEqual(e.breached, d.breached);
        node_assert_1.default.strictEqual(e.observed_display, d.observed_display);
        // Slack/margin parity check (tolerate small float math differences up to 4 decimals)
        node_assert_1.default.ok(Math.abs(e.margin - d.margin) < 1e-4, `Margin mismatch on ${e.rule_id}: ${e.margin} vs ${d.margin}`);
        node_assert_1.default.ok(Math.abs(e.slack - d.slack) < 1e-4, `Slack mismatch on ${e.rule_id}: ${e.slack} vs ${d.slack}`);
    }
});
