"use strict";
/**
 * Public-runtime contracts for a one-applicant diagnostic audit.
 *
 * The Python implementation remains the executable conformance reference while the
 * TypeScript runner is ported family by family. These records deliberately accept only
 * fictional financial facts: there is no name, address, free text, identifier, upload,
 * demographic field, or account number anywhere in the public request shape.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.AUDIT_CONFIGURATIONS = exports.PUBLIC_RECORD_KINDS = exports.EMPLOYMENT_STATUSES = exports.AUDIT_FAMILIES = void 0;
exports.AUDIT_FAMILIES = [
    "policy_adherence",
    "monotonicity",
    "invariance",
    "serialization",
    "counterfactual_bias",
    "reason_validity",
];
exports.EMPLOYMENT_STATUSES = [
    "FULL_TIME",
    "PART_TIME",
    "SELF_EMPLOYED",
    "CONTRACT",
    "RETIRED",
    "UNEMPLOYED",
];
exports.PUBLIC_RECORD_KINDS = ["NONE", "COLLECTION", "TAX_LIEN", "JUDGMENT", "BANKRUPTCY_CH7", "BANKRUPTCY_CH13"];
exports.AUDIT_CONFIGURATIONS = [
    {
        id: "baseline",
        label: "Structured baseline",
        description: "The policy and application are supplied together; the model submits one structured decision without audit tools.",
        toolsEnabled: false,
    },
    {
        id: "platform",
        label: "Tool-guided platform",
        description: "The same policy is supplied with auditable tools and required-tool checks before a decision is accepted.",
        toolsEnabled: true,
    },
];
