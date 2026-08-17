import { getRuntimeConfiguration } from "@/lib/audit/runtime";

type RedisResponse<T> = { result?: T; error?: string };

async function command<T>(args: readonly (string | number)[]): Promise<T> {
  const config = getRuntimeConfiguration();
  const response = await fetch(config.redisUrl, {
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

export const redis = {
  get: (key: string) => command<string | null>(["GET", key]),
  set: (key: string, value: string, ttlSeconds: number) => command<"OK">(["SET", key, value, "EX", ttlSeconds]),
  del: (key: string) => command<number>(["DEL", key]),
  eval: <T>(script: string, keys: readonly string[], args: readonly (string | number)[]) => command<T>(["EVAL", script, keys.length, ...keys, ...args]),
};
