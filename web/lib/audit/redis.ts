import { getRuntimeConfiguration } from "@/lib/audit/runtime";

type RedisResponse<T> = { result?: T; error?: string };

// Typed alias so callers can reference it without importing globalThis.fetch directly.
export type FetchFn = typeof globalThis.fetch;

/**
 * Creates a Redis HTTP client that uses the provided `fetchFn`.
 *
 * This indirection is required because Vercel Workflows intercepts and blocks
 * the global `fetch` inside "use step" / "use workflow" functions.
 * Workflow code must import `fetch` from "workflow" and pass it here;
 * normal API-route code passes `globalThis.fetch` (or omits the argument).
 */
export function createRedis(fetchFn: FetchFn) {
  async function command<T>(args: readonly (string | number)[]): Promise<T> {
    const config = getRuntimeConfiguration();
    const response = await fetchFn(config.redisUrl, {
      method: "POST",
      headers: { authorization: `Bearer ${config.redisToken}`, "content-type": "application/json" },
      body: JSON.stringify(args),
      cache: "no-store",
    });
    if (!response.ok) throw new Error("Encrypted job storage is unavailable.");
    const body = await response.json() as RedisResponse<T>;
    if (body.error) throw new Error("Encrypted job storage rejected the request.");
    return body.result as T;
  }

  return {
    get: (key: string) => command<string | null>(["GET", key]),
    set: (key: string, value: string, ttlSeconds: number) => command<"OK">(["SET", key, value, "EX", ttlSeconds]),
    del: (key: string) => command<number>(["DEL", key]),
    eval: <T>(script: string, keys: readonly string[], args: readonly (string | number)[]) =>
      command<T>(["EVAL", script, keys.length, ...keys, ...args]),
  };
}

/** Default singleton using the global fetch — safe for API routes. */
export const redis = createRedis(globalThis.fetch);
