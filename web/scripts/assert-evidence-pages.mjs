import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const runsRoot = join(process.cwd(), ".next/server/app/r");
const pairPages = [];

for (const run of readdirSync(runsRoot, { withFileTypes: true })) {
  if (!run.isDirectory()) continue;
  const pairsRoot = join(runsRoot, run.name, "pairs");
  if (!existsSync(pairsRoot)) continue;
  for (const file of readdirSync(pairsRoot).filter((name) => name.endsWith(".html"))) {
    pairPages.push(join(pairsRoot, file));
  }
}

if (pairPages.length === 0) throw new Error("No paired-evidence pages were generated");

for (const page of pairPages) {
  const html = readFileSync(page, "utf8");
  if (html.includes('id="__next_error__"') || !html.includes("Paired evidence")) {
    throw new Error(`Paired-evidence page rendered an error: ${page}`);
  }
}

console.log(`${pairPages.length} paired-evidence pages rendered`);
