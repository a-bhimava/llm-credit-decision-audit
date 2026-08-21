import { cache } from "react";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { notFound } from "next/navigation";

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type JsonObject = Record<string, Json>;

export type RunIndexEntry = {
  run_id: string;
  label: string;
  kind: "scripted" | "model";
  evidence_label: string | null;
  suite: string;
  created_at: string;
  path: string;
  headline_id: string | null;
  validates_harness: boolean;
  validated_by_run_id: string | null;
  can_be_default: boolean;
  counts: { applicants: number; episodes: number; tests: number; pairs: number };
  model: { provider: string; model_id: string; temperature: number | null };
};

export type RunIndex = {
  default_run_id: string;
  runs: RunIndexEntry[];
};

const evidenceRoot = path.join(process.cwd(), "public", "runs");

function object(value: Json, label: string): JsonObject {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`Expected an object in ${label}`);
  }
  return value as JsonObject;
}

function string(value: Json | undefined, label: string): string {
  if (typeof value !== "string") throw new Error(`Expected a string in ${label}`);
  return value;
}

function array(value: Json | undefined, label: string): Json[] {
  if (!Array.isArray(value)) throw new Error(`Expected an array in ${label}`);
  return value;
}

async function jsonFile(relative: string): Promise<JsonObject> {
  if (path.isAbsolute(relative) || relative.split("/").includes("..")) {
    throw new Error(`Unsafe evidence path: ${relative}`);
  }
  const raw = await readFile(path.join(evidenceRoot, relative), "utf8");
  return object(JSON.parse(raw) as Json, relative);
}

export const loadRunIndex = cache(async (): Promise<RunIndex> => {
  const payload = await jsonFile("index.json");
  if (payload.schema !== "credit-audit/run-index@1") {
    throw new Error("Unsupported run-index schema");
  }
  const runs = array(payload.runs, "runs").map((candidate) => {
    const entry = object(candidate, "run index entry");
    const counts = object(entry.counts, "run counts");
    const model = object(entry.model, "run model");
    const kind = string(entry.kind, "run kind");
    if (kind !== "scripted" && kind !== "model") throw new Error("Unsupported run kind");
    return {
      run_id: string(entry.run_id, "run_id"),
      label: string(entry.label, "label"),
      kind,
      evidence_label:
        entry.evidence_label === null ? null : string(entry.evidence_label, "evidence_label"),
      suite: string(entry.suite, "suite"),
      created_at: string(entry.created_at, "created_at"),
      path: string(entry.path, "path"),
      headline_id: entry.headline_id === null ? null : string(entry.headline_id, "headline_id"),
      validates_harness: entry.validates_harness === true,
      validated_by_run_id:
        entry.validated_by_run_id === null
          ? null
          : string(entry.validated_by_run_id, "validated_by_run_id"),
      can_be_default: entry.can_be_default === true,
      counts: {
        applicants: Number(counts.applicants),
        episodes: Number(counts.episodes),
        tests: Number(counts.tests),
        pairs: Number(counts.pairs),
      },
      model: {
        provider: string(model.provider, "model.provider"),
        model_id: string(model.model_id, "model.model_id"),
        temperature: model.temperature === null ? null : Number(model.temperature),
      },
    } satisfies RunIndexEntry;
  });
  return { default_run_id: string(payload.default_run_id, "default_run_id"), runs };
});

export const getRun = cache(async (runId: string): Promise<RunIndexEntry> => {
  const index = await loadRunIndex();
  const run = index.runs.find((candidate) => candidate.run_id === runId);
  if (!run) notFound();
  return run;
});

export const getManifest = cache(async (runId: string): Promise<JsonObject> => {
  await getRun(runId);
  const manifest = await jsonFile(`${runId}/manifest.json`);
  if (manifest.schema !== "credit-audit/manifest@1") throw new Error("Unsupported manifest schema");
  return manifest;
});

export const getSummary = cache(async (runId: string): Promise<JsonObject | null> => {
  try {
    await getRun(runId);
    const summary = await jsonFile(`${runId}/summary.json`);
    if (summary.schema !== "credit-audit/summary@1") throw new Error("Unsupported summary schema");
    return summary;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
});

export const getEstimates = cache(async (runId: string, agent?: string): Promise<JsonObject | null> => {
  try {
    await getRun(runId);
    const estimates = await jsonFile(`${runId}/stats/estimates.json`);
    if (estimates.schema !== "credit-audit/estimates@1") {
      throw new Error("Unsupported estimates schema");
    }
    return estimates;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
});

export const getCheckIndex = cache(async (runId: string): Promise<JsonObject | null> => {
  try {
    await getRun(runId);
    const index = await jsonFile(`${runId}/checks/index.json`);
    if (index.schema !== "credit-audit/check-index@1") throw new Error("Unsupported check-index schema");
    return index;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
});

export const getIntegrity = cache(async (runId: string): Promise<JsonObject> =>
  getRun(runId).then(() => jsonFile(`${runId}/integrity/chain.json`)),
);

export const getDefects = cache(async (runId: string): Promise<JsonObject | null> => {
  try {
    await getRun(runId);
    const defects = await jsonFile(`${runId}/planted-defects.json`);
    if (defects.schema !== "credit-audit/planted-defects@1") throw new Error("Unsupported defects schema");
    return defects;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
});

export const getPairs = cache(async (runId: string): Promise<JsonObject[]> => {
  await getRun(runId);
  const directory = path.join(evidenceRoot, runId, "pairs");
  try {
    const files = (await readdir(directory)).filter((name) => name.endsWith(".json")).sort();
    return Promise.all(files.map((name) => jsonFile(`${runId}/pairs/${name}`)));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
});

export const getPair = cache(async (runId: string, pairId: string, agent?: string): Promise<JsonObject> => {
  const pairs = await getPairs(runId);
  const pair = pairs.find((candidate) => candidate.pair_id === pairId);
  if (!pair) notFound();
  return pair;
});

export const getChecks = cache(async (runId: string, agent?: string): Promise<JsonObject[]> => {
  const index = await getCheckIndex(runId);
  if (!index) return [];
  return array(index.checks, "checks").map((entry) => object(entry, "check"));
});

export const getCheckRows = cache(async (runId: string, check: string, agent?: string): Promise<JsonObject> => {
  const checks = await getChecks(runId);
  if (!checks.some((entry) => entry.check === check)) notFound();
  return jsonFile(agent ? `${runId}/agents/${agent}/checks/rows/${check}.json` : `${runId}/checks/rows/${check}.json`);
});

/** Decode the compact check-row export without changing its on-disk evidence. */
export function decodeCheckRows(document: JsonObject): JsonObject[] {
  const columns = array(document.columns, "check row columns").map((value) =>
    string(value, "check row column"),
  );
  const dictionary = document.dict === undefined ? {} : object(document.dict, "check row dictionary");
  return array(document.rows, "check rows").map((candidate) => {
    const values = array(candidate, "check row");
    if (values.length !== columns.length) throw new Error("Check row does not match its declared columns");
    return Object.fromEntries(columns.map((column, index) => {
      const raw = values[index];
      const lookup = dictionary[column];
      if (lookup !== undefined) {
        const dictionaryValues = array(lookup, `dictionary ${column}`);
        if (typeof raw !== "number" || !Number.isInteger(raw) || dictionaryValues[raw] === undefined) {
          throw new Error(`Invalid dictionary value for ${column}`);
        }
        return [column, dictionaryValues[raw]];
      }
      return [column, raw];
    })) as JsonObject;
  });
}

export function entries(value: Json | undefined, label: string): JsonObject[] {
  return array(value, label).map((entry) => object(entry, label));
}

export function field(value: JsonObject, key: string, fallback = "—"): string {
  const candidate = value[key];
  if (candidate === null || candidate === undefined) return fallback;
  if (typeof candidate === "string" || typeof candidate === "number") return String(candidate);
  return fallback;
}

export function percent(value: Json | undefined, digits = 1): string {
  return typeof value === "number" ? `${(value * 100).toFixed(digits)}%` : "—";
}

export function displayDate(value: string): string {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value));
}
