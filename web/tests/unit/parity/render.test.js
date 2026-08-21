"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const node_test_1 = __importDefault(require("node:test"));
const node_assert_1 = __importDefault(require("node:assert"));
const node_fs_1 = __importDefault(require("node:fs"));
const node_path_1 = __importDefault(require("node:path"));
const packet_1 = require("../../../lib/audit/render/packet");
const json_1 = require("../../../lib/audit/render/json");
(0, node_test_1.default)("Render Packet Parity", () => {
    const fixturePath = node_path_1.default.join(__dirname, "../../fixtures/render.json");
    const data = JSON.parse(node_fs_1.default.readFileSync(fixturePath, "utf-8"));
    const idsPath = node_path_1.default.join(__dirname, "../../fixtures/ids.json");
    const appData = JSON.parse(node_fs_1.default.readFileSync(idsPath, "utf-8")).applicant;
    const app = {
        applicant_id: appData.applicant_id,
        facts: appData.facts,
        presentation: appData.presentation,
        dti: { toString: () => appData.dti ?? data.packet.income.debt_to_income_ratio },
        utilization: { toString: () => appData.utilization ?? data.packet.credit_file.revolving.utilization },
        cltv: { toString: () => appData.cltv ?? "0" }
    };
    const p = (0, packet_1.buildApplicationPacket)(app);
    node_assert_1.default.deepStrictEqual(p, data.packet);
});
(0, node_test_1.default)("Render JSON Parity", () => {
    const idsPath = node_path_1.default.join(__dirname, "../../fixtures/ids.json");
    const appData = JSON.parse(node_fs_1.default.readFileSync(idsPath, "utf-8")).applicant;
    const data = JSON.parse(node_fs_1.default.readFileSync(node_path_1.default.join(__dirname, "../../fixtures/render.json"), "utf-8"));
    const app = {
        applicant_id: appData.applicant_id,
        facts: appData.facts,
        presentation: appData.presentation,
        dti: { toString: () => appData.dti ?? data.packet.income.debt_to_income_ratio },
        utilization: { toString: () => appData.utilization ?? data.packet.credit_file.revolving.utilization },
        cltv: { toString: () => appData.cltv ?? "0" }
    };
    const str = (0, json_1.renderJson)(app, "json");
    node_assert_1.default.strictEqual(str, data.json_str_sorted);
    const strShuffled = (0, json_1.renderJson)(app, "json", { json_field_order_seed: 42 });
    node_assert_1.default.strictEqual(strShuffled, data.json_str_shuffled);
});
