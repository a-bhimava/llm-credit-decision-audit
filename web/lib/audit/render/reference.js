"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.applicantReference = applicantReference;
exports.applicantReferenceFor = applicantReferenceFor;
const ids_1 = require("../ids");
function applicantReference(applicantId) {
    const digest = (0, ids_1.contentId)(applicantId, 16);
    const hexPart = digest.split(":")[1];
    return `MPL-${hexPart.slice(0, 10).toUpperCase()}`;
}
function applicantReferenceFor(applicant) {
    return applicantReference(applicant.applicant_id);
}
