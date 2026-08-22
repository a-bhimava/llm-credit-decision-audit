// Uses Web Crypto API (crypto.subtle) so this module is safe to import
// in workflow step functions — no node:crypto at module root.

import type { AuditIntake, AuditJobView, AuditPreflight, AuditProgress } from "@/lib/audit/contracts";
import { redis } from "@/lib/audit/redis";
import { getRuntimeConfiguration, secureEqual } from "@/lib/audit/runtime";

const TTL_SECONDS = 60 * 60;
const JOB_PREFIX = "credit-audit:job:";
const DAILY_PREFIX = "credit-audit:daily:";

type StoredJob = Readonly<{
  id: string;
  input: AuditIntake;
  preflight: AuditPreflight;
  createdAt: string;
  expiresAt: string;
  progress: AuditProgress;
  workflowRunId?: string;
}>;

function key(id: string) { return `${JOB_PREFIX}${id}`; }

function b64uEncode(buf: ArrayBuffer): string {
  return Buffer.from(buf).toString("base64url");
}
function b64uDecode(s: string): Buffer {
  return Buffer.from(s, "base64url");
}

async function getCryptoKey(rawKey: Buffer, usage: "encrypt" | "decrypt"): Promise<CryptoKey> {
  return crypto.subtle.importKey("raw", rawKey, { name: "AES-GCM", length: 256 }, false, [usage]);
}

async function seal(value: StoredJob): Promise<string> {
  const { encryptionKey } = getRuntimeConfiguration();
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ck = await getCryptoKey(encryptionKey, "encrypt");
  const plaintext = new TextEncoder().encode(JSON.stringify(value));
  const cipherBuf = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, ck, plaintext);
  // AES-GCM appends the 16-byte auth tag at the end of cipherBuf
  const cipherBytes = new Uint8Array(cipherBuf);
  const ciphertext = cipherBytes.slice(0, -16);
  const tag = cipherBytes.slice(-16);
  return [b64uEncode(iv), b64uEncode(tag), b64uEncode(ciphertext)].join(".");
}

async function open(value: string): Promise<StoredJob> {
  const { encryptionKey } = getRuntimeConfiguration();
  const [ivPart, tagPart, ciphertextPart] = value.split(".");
  if (!ivPart || !tagPart || !ciphertextPart) throw new Error("Stored audit payload is malformed.");
  const iv = b64uDecode(ivPart);
  const tag = b64uDecode(tagPart);
  const ct = b64uDecode(ciphertextPart);
  // Reassemble ciphertext+tag for SubtleCrypto
  const combined = Buffer.concat([ct, tag]);
  const ck = await getCryptoKey(encryptionKey, "decrypt");
  const plainBuf = await crypto.subtle.decrypt({ name: "AES-GCM", iv }, ck, combined);
  return JSON.parse(new TextDecoder().decode(plainBuf)) as StoredJob;
}

async function hmacSign(key: Buffer, payload: string): Promise<string> {
  const ck = await crypto.subtle.importKey("raw", key, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", ck, new TextEncoder().encode(payload));
  return b64uEncode(sig);
}

async function token(id: string, expiresAt: string): Promise<string> {
  const { encryptionKey } = getRuntimeConfiguration();
  const payload = `${id}.${expiresAt}`;
  const sig = await hmacSign(encryptionKey, payload);
  return `${payload}.${sig}`;
}

export async function validSessionToken(id: string, expiresAt: string, supplied: string | undefined): Promise<boolean> {
  if (!supplied || new Date(expiresAt).getTime() < Date.now()) return false;
  const expected = await token(id, expiresAt);
  return secureEqual(expected, supplied);
}

export async function createAuditJob(input: AuditIntake, preflight: AuditPreflight): Promise<{ job: AuditJobView; sessionToken: string }> {
  const id = crypto.randomUUID();
  const createdAt = new Date().toISOString();
  const expiresAt = new Date(Date.now() + TTL_SECONDS * 1_000).toISOString();
  const progress: AuditProgress = { status: "queued", completedEpisodes: 0, plannedEpisodesUpper: preflight.plannedEpisodesUpper, spentUsd: 0, message: "Accepted for planning." };
  const stored: StoredJob = { id, input, preflight, createdAt, expiresAt, progress };
  await redis.set(key(id), await seal(stored), TTL_SECONDS);
  return { job: toView(stored), sessionToken: await token(id, expiresAt) };
}

export async function readAuditJob(id: string): Promise<StoredJob | null> {
  const encrypted = await redis.get(key(id));
  return encrypted ? open(encrypted) : null;
}

export async function updateAuditJob(id: string, update: (current: StoredJob) => StoredJob): Promise<StoredJob> {
  const current = await readAuditJob(id);
  if (!current) throw new Error("Audit session expired.");
  const remaining = Math.max(1, Math.ceil((new Date(current.expiresAt).getTime() - Date.now()) / 1_000));
  const next = update(current);
  await redis.set(key(id), await seal(next), remaining);
  return next;
}

export function toView(job: StoredJob): AuditJobView {
  return { id: job.id, expiresAt: job.expiresAt, preflight: job.preflight, progress: job.progress, workflowRunId: job.workflowRunId };
}

const RESERVE_DAILY_SPEND = `
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local amount = tonumber(ARGV[1])
local cap = tonumber(ARGV[2])
if current + amount > cap then return 0 end
redis.call('INCRBYFLOAT', KEYS[1], amount)
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1`;

/** Atomic daily reservation. Actual settlement/release will be part of the runner port. */
export async function reserveDailySpend(upperUsd: number, capUsd: number): Promise<boolean> {
  const day = new Date().toISOString().slice(0, 10);
  const now = new Date();
  const tomorrow = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1);
  const ttl = Math.max(60, Math.ceil((tomorrow - now.getTime()) / 1_000));
  return (await redis.eval<number>(RESERVE_DAILY_SPEND, [`${DAILY_PREFIX}${day}`], [upperUsd, capUsd, ttl])) === 1;
}
