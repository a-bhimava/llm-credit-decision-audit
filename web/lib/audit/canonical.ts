import { createHash } from "node:crypto";

/**
 * Deterministic JSON for the TypeScript port. Intake and episode IDs currently consist of
 * strings, booleans, and integer cents only; rejecting other number forms is intentional
 * until the Python float canonicalisation vectors are ported verbatim.
 */
function normalize(value: unknown): unknown {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) throw new TypeError("canonical values must be safe integers");
    return value;
  }
  if (Array.isArray(value)) return value.map(normalize);
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    return Object.fromEntries(Object.keys(record).sort().map((key) => [key, normalize(record[key])]));
  }
  throw new TypeError(`cannot canonicalize ${typeof value}`);
}

export function canonicalJson(value: unknown): string {
  return JSON.stringify(normalize(value));
}

export function contentId(value: unknown): string {
  const hash = createHash("blake2b512", { outputLength: 16 });
  hash.update(canonicalJson(value), "utf8");
  return `blake2b128:${hash.digest("hex")}`;
}

export function deriveSeed(runSeed: number, ...parts: readonly (string | number)[]): bigint {
  const hash = createHash("blake2b512", { outputLength: 8 });
  hash.update(String(runSeed), "utf8");
  for (const part of parts) {
    hash.update("\u001f", "utf8");
    hash.update(String(part), "utf8");
  }
  return BigInt(`0x${hash.digest("hex")}`) & ((1n << 63n) - 1n);
}
