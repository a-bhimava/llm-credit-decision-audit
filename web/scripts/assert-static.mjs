import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd();
const fail = (message) => {
  console.error(`static-site assertion failed: ${message}`);
  process.exitCode = 1;
};

const forbiddenPaths = ["middleware.ts", "middleware.js", "proxy.ts", "proxy.js", "app/api"];
for (const relative of forbiddenPaths) {
  if (existsSync(join(root, relative))) {
    fail(`${relative} is forbidden: the evidence site must not ship a dynamic request layer`);
  }
}

const scanSource = (directory) => {
  for (const entry of readdirSync(directory)) {
    const target = join(directory, entry);
    if (statSync(target).isDirectory()) {
      scanSource(target);
    } else if (/^route\.[cm]?[jt]sx?$/.test(entry)) {
      fail(`route handler is forbidden: ${target}`);
    } else if (/\.[cm]?[jt]sx?$/.test(entry) && /^\s*["']use server["'];?/m.test(readFileSync(target, "utf8"))) {
      fail(`server action module is forbidden: ${target}`);
    }
  }
};

scanSource(join(root, "app"));

const manifestPath = join(root, ".next", "prerender-manifest.json");
if (!existsSync(manifestPath)) {
  fail("missing .next/prerender-manifest.json");
} else {
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  for (const [route, details] of Object.entries(manifest.dynamicRoutes ?? {})) {
    if (details.fallback !== false) {
      fail(`dynamic fallback remains for ${route}`);
    }
  }
  if (!manifest.routes?.["/_not-found"]) {
    fail("the static not-found route was not prerendered");
  }
}

const middlewareManifestPath = join(root, ".next", "server", "middleware-manifest.json");
if (existsSync(middlewareManifestPath)) {
  const middleware = JSON.parse(readFileSync(middlewareManifestPath, "utf8"));
  if (Object.keys(middleware.middleware ?? {}).length > 0) {
    fail("middleware was emitted");
  }
  if (Object.keys(middleware.functions ?? {}).length > 0) {
    fail("server functions were emitted");
  }
}

if (!process.exitCode) {
  console.log("static-site assertion passed");
}
