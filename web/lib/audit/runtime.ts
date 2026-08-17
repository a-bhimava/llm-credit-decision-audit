import { timingSafeEqual } from "node:crypto";

export class RuntimeConfigurationError extends Error {}

export type RuntimeConfiguration = Readonly<{
  vertexApiKey: string;
  encryptionKey: Buffer;
  redisUrl: string;
  redisToken: string;
}>;

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new RuntimeConfigurationError(`${name} is not configured for this private preview.`);
  return value;
}

export function getRuntimeConfiguration(): RuntimeConfiguration {
  if (process.env.LIVE_AUDITS_ENABLED !== "true") {
    throw new RuntimeConfigurationError("Live audits are disabled in this deployment. Private-preview access must be enabled explicitly.");
  }
  if (process.env.TYPESCRIPT_AUDIT_ENGINE_ENABLED !== "true") {
    throw new RuntimeConfigurationError("The TypeScript audit engine is not enabled yet. The current deployment will not run a partial audit.");
  }
  const key = Buffer.from(required("AUDIT_SESSION_ENCRYPTION_KEY"), "base64");
  if (key.length !== 32) throw new RuntimeConfigurationError("AUDIT_SESSION_ENCRYPTION_KEY must be a base64-encoded 32-byte key.");
  return {
    vertexApiKey: required("VERTEX_API_KEY"),
    encryptionKey: key,
    redisUrl: required("UPSTASH_REDIS_REST_URL").replace(/\/$/, ""),
    redisToken: required("UPSTASH_REDIS_REST_TOKEN"),
  };
}

export function secureEqual(a: string, b: string): boolean {
  const left = Buffer.from(a);
  const right = Buffer.from(b);
  return left.length === right.length && timingSafeEqual(left, right);
}
