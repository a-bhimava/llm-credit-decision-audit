"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.EMBEDDING_CONFIDENCE_FLOOR = void 0;
exports.mapReason = mapReason;
const codes_1 = require("./codes");
const lexicon_1 = require("./lexicon");
const policy_1 = require("./policy");
exports.EMBEDDING_CONFIDENCE_FLOOR = 0.35;
function tokenize(text) {
    const match = text.toLowerCase().match(/[a-z0-9]+/g);
    return match || [];
}
function cosineSimilarity(a, b) {
    let numerator = 0;
    for (const t of Object.keys(a)) {
        if (b[t])
            numerator += a[t] * b[t];
    }
    let normA = 0;
    for (const v of Object.values(a))
        normA += v * v;
    let normB = 0;
    for (const v of Object.values(b))
        normB += v * v;
    if (normA === 0 || normB === 0)
        return 0.0;
    return numerator / (Math.sqrt(normA) * Math.sqrt(normB));
}
let referenceVectorCache = null;
let referenceVectorHash = null;
function getReferenceVectors() {
    // policy isn't dynamic, so we just build it once
    if (referenceVectorCache)
        return referenceVectorCache;
    const vectors = [];
    const meta = (0, codes_1.getCodeMeta)();
    for (const code of Object.keys(meta)) {
        const rules = policy_1.policy.rules.filter(r => r.reason_code === code);
        if (rules.length === 0)
            continue;
        let text = rules.map(r => r.statement).join(" ");
        if (meta[code].form_c1_phrase) {
            text += " " + meta[code].form_c1_phrase;
        }
        const tokens = tokenize(text);
        const counts = {};
        for (const t of tokens) {
            counts[t] = (counts[t] || 0) + 1;
        }
        vectors.push([code, counts]);
    }
    referenceVectorCache = vectors;
    return vectors;
}
function split(rawText) {
    // /\\s*(?:;|\\n|(?<=[A-Za-z])\\s+and\\s+(?=[A-Za-z]))\\s*/gi
    // JS regex doesn't support lookbehinds fully in all envs historically but ES2018+ supports it.
    const re = /\s*(?:;|\n|(?<=[a-z])\s+and\s+(?=[a-z]))\s*/gi;
    return rawText.split(re).map(s => s.trim()).filter(s => s.length > 0);
}
function containsPattern(textLower, patterns) {
    for (const p of patterns) {
        if (textLower.includes(p))
            return true;
    }
    return false;
}
function lexiconClassify(text) {
    const textLower = text.toLowerCase();
    if (containsPattern(textLower, lexicon_1.lexicon.prohibited_basis_patterns))
        return "PROHIBITED_BASIS_ADJACENT";
    if (containsPattern(textLower, lexicon_1.lexicon.collateral_patterns))
        return "COLLATERAL_VALUE_INSUFFICIENT";
    if (containsPattern(textLower, lexicon_1.lexicon.out_of_schema_patterns))
        return "OUT_OF_SCHEMA_FACTOR";
    if (containsPattern(textLower, lexicon_1.lexicon.out_of_policy_patterns))
        return "OUT_OF_POLICY_FACTOR";
    for (const entry of lexicon_1.lexicon.code_patterns) {
        if (containsPattern(textLower, entry.patterns))
            return entry.code;
    }
    if (containsPattern(textLower, lexicon_1.lexicon.vague_patterns))
        return "NON_SPECIFIC_INTERNAL_POLICY";
    return null;
}
function embeddingClassify(text) {
    const tokens = tokenize(text);
    if (tokens.length === 0)
        return [null, 0.0];
    const counts = {};
    for (const t of tokens)
        counts[t] = (counts[t] || 0) + 1;
    let bestCode = null;
    let bestScore = 0.0;
    for (const [code, reference] of getReferenceVectors()) {
        const score = cosineSimilarity(counts, reference);
        if (score > bestScore) {
            bestScore = score;
            bestCode = code;
        }
    }
    if (bestCode !== null && bestScore >= exports.EMBEDDING_CONFIDENCE_FLOOR) {
        return [bestCode, bestScore];
    }
    return [null, bestScore];
}
function classifyClause(text) {
    const lexCode = lexiconClassify(text);
    if (lexCode)
        return [lexCode, "lexicon", 1.0];
    const [embedCode, score] = embeddingClassify(text);
    if (embedCode)
        return [embedCode, "embedding", score]; // wait, mappingmethod enum?
    // the python enum translates "embedding" to "embedding" or "lexicon" ? Wait!
    // Python: MappingMethod.LEXICON, MappingMethod.EMBEDDING, MappingMethod.LLM_REMAP
    // Wait, in records.ts I typed MappingMethod as "lexicon" | "embedding" | "unmapped"!
    return ["OTHER_UNMAPPED", "unmapped", 0.0];
}
function remerge(clauses) {
    if (clauses.length <= 1)
        return Object.freeze(clauses);
    const merged = [clauses[0]];
    for (let i = 1; i < clauses.length; i++) {
        const clause = clauses[i];
        const prior = merged[merged.length - 1];
        if (clause.code === prior.code) {
            merged[merged.length - 1] = Object.freeze({
                ...prior,
                text: `${prior.text}; ${clause.text}`,
                confidence: Math.min(prior.confidence, clause.confidence)
            });
        }
        else {
            merged.push(clause);
        }
    }
    return Object.freeze(merged);
}
function mapReason(rawText) {
    const clauseTexts = split(rawText);
    if (clauseTexts.length === 0)
        return Object.freeze([]);
    const isSplit = clauseTexts.length > 1;
    const rawClauses = [];
    for (const text of clauseTexts) {
        let [code, method, confidence] = classifyClause(text);
        // records.ts has MappingMethod = "lexicon" | "embedding" | "unmapped"
        // we translate from python's LEXICON/EMBEDDING
        if (method === "lexicon")
            method = "lexicon"; // already keyword
        else if (method === "embedding")
            method = "embedding"; // actually it's embedding in python but we use llm? Let's check python!
        rawClauses.push(Object.freeze({
            text,
            code,
            method,
            confidence,
            split: isSplit
        }));
    }
    return remerge(rawClauses);
}
