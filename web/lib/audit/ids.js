"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.deriveSeed = exports.contentId = exports.canonicalJson = void 0;
exports.shortId = shortId;
exports.applicantContentId = applicantContentId;
exports.episodeInputHash = episodeInputHash;
exports.trajectoryContentId = trajectoryContentId;
exports.clusterIdFor = clusterIdFor;
const blakejs_1 = require("blakejs");
const canonical_1 = require("./canonical");
Object.defineProperty(exports, "canonicalJson", { enumerable: true, get: function () { return canonical_1.canonicalJson; } });
Object.defineProperty(exports, "contentId", { enumerable: true, get: function () { return canonical_1.contentId; } });
Object.defineProperty(exports, "deriveSeed", { enumerable: true, get: function () { return canonical_1.deriveSeed; } });
function shortId(obj, length = 8) {
    const hex = (0, blakejs_1.blake2bHex)(Buffer.from((0, canonical_1.canonicalJson)(obj), "utf8"), undefined, 16);
    return hex.slice(0, length);
}
function applicantContentId(applicant) {
    return (0, canonical_1.contentId)({ facts: applicant.facts, presentation: applicant.presentation });
}
function episodeInputHash(applicant, applicationText, applicantRef, renderMode) {
    return (0, canonical_1.contentId)({
        applicant_content_id: applicantContentId(applicant),
        application_text: applicationText,
        applicant_ref: applicantRef,
        render_mode: renderMode,
    });
}
function trajectoryContentId(episodeId, messages, toolCalls, decision, termination) {
    const semanticToolCalls = toolCalls.map(call => ({
        call_id: call.call_id,
        turn_index: call.turn_index,
        step: call.step,
        name: call.name,
        arguments: call.arguments,
        result: call.result,
        ok: call.ok,
        error: call.error,
    }));
    return (0, canonical_1.contentId)({
        episode_id: episodeId,
        messages,
        tool_calls: semanticToolCalls,
        decision,
        termination,
    });
}
function clusterIdFor(applicant) {
    const root = applicant.provenance.parent_applicant_id || applicant.applicant_id;
    return `cluster_${shortId({ source_applicant_id: root }, 16)}`;
}
