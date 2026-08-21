import { blake2bHex, blake2bInit, blake2bUpdate, blake2bFinal } from "blakejs";

/**
 * Lossless, platform-stable IEEE-754 hexadecimal form for floats, for hash inputs.
 * Ported from Python's float.hex().
 */
function floatHex(value: number): string {
  if (value === 0) {
    return Object.is(value, -0) ? "-0x0.0p+0" : "0x0.0p+0";
  }
  
  // A simplified exact replication of float.hex() in Python.
  // JS doesn't have an exact equivalent, so we write a small hex converter.
  // Python float.hex() format: [-]0x1.[fraction]p[exponent]
  
  const isNegative = value < 0;
  const abs = Math.abs(value);
  
  // Python float.hex() normalizes the mantissa between 1 and 2 (unless subnormal)
  let exponent = Math.floor(Math.log2(abs));
  
  let mantissa = abs / Math.pow(2, exponent);
  
  // Adjust for edge cases where mantissa >= 2 due to rounding
  if (mantissa >= 2) {
    mantissa /= 2;
    exponent++;
  } else if (mantissa < 1 && abs !== 0) {
    // subnormal numbers
    mantissa *= 2;
    exponent--;
  }

  // Multiply by 2^52 to get the exact integer bits
  const fractionBits = Math.round((mantissa - 1) * Math.pow(2, 52));
  
  // Python strips trailing zeros from the hex string
  let hexFraction = fractionBits.toString(16).padStart(13, "0");
  hexFraction = hexFraction.replace(/0+$/, "");
  if (hexFraction === "") hexFraction = "0";

  return `${isNegative ? "-" : ""}0x1.${hexFraction}p${exponent > 0 ? "+" : ""}${exponent}`;
}

/**
 * Deterministic JSON for the TypeScript port.
 */
function normalize(value: unknown): unknown {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number") {
    if (Number.isSafeInteger(value)) return value;
    if (!Number.isFinite(value)) throw new TypeError("non-finite float cannot be canonicalized");
    return floatHex(value);
  }
  if (Array.isArray(value)) return value.map(normalize);
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    return Object.fromEntries(Object.keys(record).sort().map((key) => [key, normalize(record[key])]));
  }
  throw new TypeError(`cannot canonicalize ${typeof value}`);
}

export function canonicalJson(value: unknown): string {
  return JSON.stringify(normalize(value), (key, val) => val);
}

export function contentId(value: unknown, digestSize = 16): string {
  const jsonStr = canonicalJson(value);
  // Remove spaces since stringify might add some (wait, no it doesn't without indent).
  // But JSON.stringify(floatHex) will add quotes around the hex float, which is what we want because Python canonicalizes floats to string!
  const hex = blake2bHex(Buffer.from(jsonStr, "utf8"), undefined, digestSize);
  return `blake2b${digestSize * 8}:${hex}`;
}

export function deriveSeed(runSeed: number, ...parts: readonly (string | number)[]): bigint {
  const ctx = blake2bInit(8);
  blake2bUpdate(ctx, Buffer.from(String(runSeed), "utf8"));
  for (const part of parts) {
    blake2bUpdate(ctx, Buffer.from("\u001f", "utf8"));
    blake2bUpdate(ctx, Buffer.from(String(part), "utf8"));
  }
  const digest = blake2bFinal(ctx);
  // Read big endian 8 bytes
  const buf = Buffer.from(digest);
  return buf.readBigUInt64BE() & ((1n << 63n) - 1n);
}
