import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd();
let failed = false;
const fail = (message) => { failed = true; console.error(`security-boundary assertion failed: ${message}`); };

function files(directory) {
  const output = [];
  for (const entry of readdirSync(directory)) {
    const target = join(directory, entry);
    if (statSync(target).isDirectory()) output.push(...files(target));
    else if (/\.[cm]?[jt]sx?$/.test(entry)) output.push(target);
  }
  return output;
}

for (const directory of ["app", "components", "lib", "workflows"]) {
  const target = join(root, directory);
  if (!existsSync(target)) continue;
  for (const file of files(target)) {
    const source = readFileSync(file, "utf8");
    const relative = file.slice(root.length + 1);
    if (/NEXT_PUBLIC_[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)/.test(source)) fail(`${relative} exposes a credential-shaped public environment variable`);
    if (/['\"]use client['\"]/.test(source) && /(?:VERTEX_API_KEY|AUDIT_SESSION_ENCRYPTION_KEY|UPSTASH_REDIS_REST_TOKEN)/.test(source)) fail(`${relative} references a server secret from a client module`);
    if (/app\/api\//.test(relative) && !/cache-control["']?\s*:\s*["']no-store/.test(source)) fail(`${relative} must set Cache-Control: no-store`);
  }
}

for (const route of ["app/r/[runId]/page.tsx", "app/evidence/page.tsx"]) {
  const source = readFileSync(join(root, route), "utf8");
  if (!source.includes('dynamic = "force-static"')) fail(`${route} must remain a static evidence route`);
}

if (failed) process.exitCode = 1;
else console.log("security-boundary assertion passed");
