import { getCodeMeta } from "./codes";
import { lexicon } from "./lexicon";
import { policy } from "./policy";
import { MappingMethod } from "./records";

export const EMBEDDING_CONFIDENCE_FLOOR = 0.35;

export type MappedClause = Readonly<{
  text: string;
  code: string;
  method: MappingMethod;
  confidence: number;
  split: boolean;
}>;

function tokenize(text: string): string[] {
  const match = text.toLowerCase().match(/[a-z0-9]+/g);
  return match || [];
}

function cosineSimilarity(a: Record<string, number>, b: Record<string, number>): number {
  let numerator = 0;
  for (const t of Object.keys(a)) {
    if (b[t]) numerator += a[t]! * b[t]!;
  }
  let normA = 0;
  for (const v of Object.values(a)) normA += v * v;
  let normB = 0;
  for (const v of Object.values(b)) normB += v * v;
  
  if (normA === 0 || normB === 0) return 0.0;
  return numerator / (Math.sqrt(normA) * Math.sqrt(normB));
}

let referenceVectorCache: [string, Record<string, number>][] | null = null;
let referenceVectorHash: string | null = null;

function getReferenceVectors(): [string, Record<string, number>][] {
  // policy isn't dynamic, so we just build it once
  if (referenceVectorCache) return referenceVectorCache;
  
  const vectors: [string, Record<string, number>][] = [];
  const meta = getCodeMeta();
  
  for (const code of Object.keys(meta)) {
    const rules = policy.rules.filter(r => r.reason_code === code);
    if (rules.length === 0) continue;
    
    let text = rules.map(r => r.statement).join(" ");
    if (meta[code]!.form_c1_phrase) {
      text += " " + meta[code]!.form_c1_phrase;
    }
    
    const tokens = tokenize(text);
    const counts: Record<string, number> = {};
    for (const t of tokens) {
      counts[t] = (counts[t] || 0) + 1;
    }
    vectors.push([code, counts]);
  }
  
  referenceVectorCache = vectors;
  return vectors;
}

function split(rawText: string): string[] {
  // /\\s*(?:;|\\n|(?<=[A-Za-z])\\s+and\\s+(?=[A-Za-z]))\\s*/gi
  // JS regex doesn't support lookbehinds fully in all envs historically but ES2018+ supports it.
  const re = /\s*(?:;|\n|(?<=[a-z])\s+and\s+(?=[a-z]))\s*/gi;
  return rawText.split(re).map(s => s.trim()).filter(s => s.length > 0);
}

function containsPattern(textLower: string, patterns: readonly string[]): boolean {
  for (const p of patterns) {
    if (textLower.includes(p)) return true;
  }
  return false;
}

function lexiconClassify(text: string): string | null {
  const textLower = text.toLowerCase();
  
  if (containsPattern(textLower, lexicon.prohibited_basis_patterns)) return "PROHIBITED_BASIS_ADJACENT";
  if (containsPattern(textLower, lexicon.collateral_patterns)) return "COLLATERAL_VALUE_INSUFFICIENT";
  if (containsPattern(textLower, lexicon.out_of_schema_patterns)) return "OUT_OF_SCHEMA_FACTOR";
  if (containsPattern(textLower, lexicon.out_of_policy_patterns)) return "OUT_OF_POLICY_FACTOR";
  
  for (const entry of lexicon.code_patterns) {
    if (containsPattern(textLower, entry.patterns)) return entry.code;
  }
  
  if (containsPattern(textLower, lexicon.vague_patterns)) return "NON_SPECIFIC_INTERNAL_POLICY";
  
  return null;
}

function embeddingClassify(text: string): [string | null, number] {
  const tokens = tokenize(text);
  if (tokens.length === 0) return [null, 0.0];
  
  const counts: Record<string, number> = {};
  for (const t of tokens) counts[t] = (counts[t] || 0) + 1;
  
  let bestCode: string | null = null;
  let bestScore = 0.0;
  
  for (const [code, reference] of getReferenceVectors()) {
    const score = cosineSimilarity(counts, reference);
    if (score > bestScore) {
      bestScore = score;
      bestCode = code;
    }
  }
  
  if (bestCode !== null && bestScore >= EMBEDDING_CONFIDENCE_FLOOR) {
    return [bestCode, bestScore];
  }
  return [null, bestScore];
}

function classifyClause(text: string): [string, MappingMethod, number] {
  const lexCode = lexiconClassify(text);
  if (lexCode) return [lexCode, "lexicon", 1.0];
  
  const [embedCode, score] = embeddingClassify(text);
  if (embedCode) return [embedCode, "embedding", score]; // wait, mappingmethod enum?
  // the python enum translates "embedding" to "embedding" or "lexicon" ? Wait!
  // Python: MappingMethod.LEXICON, MappingMethod.EMBEDDING, MappingMethod.LLM_REMAP
  // Wait, in records.ts I typed MappingMethod as "lexicon" | "embedding" | "unmapped"!
  
  return ["OTHER_UNMAPPED", "unmapped", 0.0];
}

function remerge(clauses: MappedClause[]): readonly MappedClause[] {
  if (clauses.length <= 1) return Object.freeze(clauses);
  const merged: MappedClause[] = [clauses[0]!];
  
  for (let i = 1; i < clauses.length; i++) {
    const clause = clauses[i]!;
    const prior = merged[merged.length - 1]!;
    if (clause.code === prior.code) {
      merged[merged.length - 1] = Object.freeze({
        ...prior,
        text: `${prior.text}; ${clause.text}`,
        confidence: Math.min(prior.confidence, clause.confidence)
      });
    } else {
      merged.push(clause);
    }
  }
  return Object.freeze(merged);
}

export function mapReason(rawText: string): readonly MappedClause[] {
  const clauseTexts = split(rawText);
  if (clauseTexts.length === 0) return Object.freeze([]);
  
  const isSplit = clauseTexts.length > 1;
  const rawClauses: MappedClause[] = [];
  
  for (const text of clauseTexts) {
    let [code, method, confidence] = classifyClause(text);
    // records.ts has MappingMethod = "lexicon" | "embedding" | "unmapped"
    // we translate from python's LEXICON/EMBEDDING
    if (method as any === "lexicon") method = "lexicon"; // already keyword
    else if ((method as any) === "embedding") method = "embedding"; // actually it's embedding in python but we use llm? Let's check python!
    
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
