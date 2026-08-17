import { createCipheriv, createDecipheriv, createHmac, randomBytes, randomUUID } from "node:crypto";
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

function seal(value: StoredJob): string {
  const { encryptionKey } = getRuntimeConfiguration();
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", encryptionKey, iv);
  const ciphertext = Buffer.concat([cipher.update(JSON.stringify(value), "utf8"), cipher.final()]);
  return [iv.toString("base64url"), cipher.getAuthTag().toString("base64url"), ciphertext.toString("base64url")].join(".");
}

function open(value: string): StoredJob {
  const { encryptionKey } = getRuntimeConfiguration();
  const [ivPart, tagPart, ciphertextPart] = value.split(".");
  if (!ivPart || !tagPart || !ciphertextPart) throw new Error("Stored audit payload is malformed.");
  const decipher = createDecipheriv("aes-256-gcm", encryptionKey, Buffer.from(ivPart, "base64url"));
  decipher.setAuthTag(Buffer.from(tagPart, "base64url"));
  return JSON.parse(Buffer.concat([decipher.update(Buffer.from(ciphertextPart, "base64url")), decipher.final()]).toString("utf8")) as StoredJob;
}

function token(id: string, expiresAt: string): string {
  const { encryptionKey } = getRuntimeConfiguration();
  const payload = `${id}.${expiresAt}`;
  const signature = createHmac("sha256", encryptionKey).update(payload).digest("base64url");
  return `${payload}.${signature}`;
}

export function validSessionToken(id: string, expiresAt: string, supplied: string | undefined): boolean {
  if (!supplied || new Date(expiresAt).getTime() < Date.now()) return false;
  return secureEqual(token(id, expiresAt), supplied);
}

export async function createAuditJob(input: AuditIntake, preflight: AuditPreflight): Promise<{ job: AuditJobView; sessionToken: string }> {
  const id = randomUUID();
  const createdAt = new Date().toISOString();
  const expiresAt = new Date(Date.now() + TTL_SECONDS * 1_000).toISOString();
  const progress: AuditProgress = { status: "queued", completedEpisodes: 0, plannedEpisodesUpper: preflight.plannedEpisodesUpper, spentUsd: 0, message: "Accepted for planning." };
  const stored: StoredJob = { id, input, preflight, createdAt, expiresAt, progress };
  await redis.set(key(id), seal(stored), TTL_SECONDS);
  return { job: toView(stored), sessionToken: token(id, expiresAt) };
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
  await redis.set(key(id), seal(next), remaining);
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
