
export class RuntimeConfigurationError extends Error {}

export type RuntimeConfiguration = Readonly<{
  vertexApiKey?: string;
  vertexProject?: string;
  vertexLocation?: string;
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
  
  const vertexApiKey = process.env.VERTEX_API_KEY;
  const vertexProject = process.env.GOOGLE_CLOUD_PROJECT;
  if (!vertexApiKey && !vertexProject) {
    throw new RuntimeConfigurationError("You must provide either VERTEX_API_KEY or GOOGLE_CLOUD_PROJECT for ADC authentication.");
  }

  return {
    vertexApiKey,
    vertexProject,
    vertexLocation: process.env.GOOGLE_CLOUD_LOCATION || "us-central1",
    encryptionKey: key,
    redisUrl: required("UPSTASH_REDIS_REST_URL").replace(/\/$/, ""),
    redisToken: required("UPSTASH_REDIS_REST_TOKEN"),
  };
}

export function secureEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let mismatch = 0;
  for (let i = 0; i < a.length; ++i) {
    mismatch |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return mismatch === 0;
}
