"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const node_test_1 = __importDefault(require("node:test"));
const node_assert_1 = __importDefault(require("node:assert"));
const map_1 = require("../../../lib/audit/map");
(0, node_test_1.default)("Map Reason Parity", () => {
    const c1 = (0, map_1.mapReason)("Income insufficient for amount of credit requested");
    node_assert_1.default.strictEqual(c1[0].code, "INSUFFICIENT_INCOME");
    node_assert_1.default.strictEqual(c1[0].method, "lexicon");
    const c2 = (0, map_1.mapReason)("Income insufficient for amount of credit requested and bankruptcy");
    node_assert_1.default.strictEqual(c2.length, 2);
    node_assert_1.default.strictEqual(c2[0].code, "INSUFFICIENT_INCOME");
    node_assert_1.default.strictEqual(c2[1].code, "BANKRUPTCY");
    const c3 = (0, map_1.mapReason)("debt obligations exceed income amount requested");
    node_assert_1.default.strictEqual(c3[0].code, "EXCESSIVE_OBLIGATIONS_DTI");
    node_assert_1.default.strictEqual(c3[0].method, "embedding");
    node_assert_1.default.ok(Math.abs(c3[0].confidence - 0.522976) < 1e-3);
    const c4 = (0, map_1.mapReason)("just completely bad file");
    node_assert_1.default.strictEqual(c4[0].code, "OTHER_UNMAPPED");
    const c5 = (0, map_1.mapReason)("the applicant's income is insufficient and their annual income does not meet the minimum");
    node_assert_1.default.strictEqual(c5.length, 1);
    node_assert_1.default.strictEqual(c5[0].code, "INSUFFICIENT_INCOME");
    node_assert_1.default.strictEqual(c5[0].split, true);
});
