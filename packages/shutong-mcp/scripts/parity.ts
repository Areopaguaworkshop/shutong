import { readFileSync } from "node:fs";
import path from "node:path";
import { SearchIndex } from "../src/search/index.ts";

interface QueryEntry {
  id: string;
  language: "zh" | "en";
  query: string;
}

interface BaselineEntry {
  id: string;
  language: "zh" | "en";
  query: string;
  hits: Array<{ node_id: string | null }>;
}

const packageRoot = path.resolve(import.meta.dirname, "..");
const corpus = path.resolve(process.env.SHUTONG_CORPUS ?? path.join(packageRoot, "../../corpus"));
const dbPath = path.resolve(
  process.env.SHUTONG_INDEX_DB ?? path.join(packageRoot, "../../.tmp/shutong-search.sqlite"),
);
const queries = JSON.parse(
  readFileSync(path.join(packageRoot, "test/fixtures/queries.json"), "utf8"),
) as QueryEntry[];
const baseline = JSON.parse(
  readFileSync(path.join(packageRoot, "test/fixtures/bm25-baseline.json"), "utf8"),
) as BaselineEntry[];
const byId = new Map(baseline.map((entry) => [entry.id, entry]));

function jaccard(left: Set<string>, right: Set<string>): number {
  if (left.size === 0 && right.size === 0) return 1;
  let intersection = 0;
  for (const value of left) if (right.has(value)) intersection += 1;
  const union = left.size + right.size - intersection;
  return union === 0 ? 1 : intersection / union;
}

const index = new SearchIndex(dbPath);
index.indexCorpus(corpus, { reset: true });

const rows = queries.map((entry) => {
  const python = byId.get(entry.id);
  const pythonIds = new Set(
    (python?.hits ?? []).map((hit) => hit.node_id).filter((id): id is string => Boolean(id)),
  );
  const tsIds = new Set(index.search(entry.query, { limit: 10 }).map((hit) => hit.node_id));
  const intersection = [...tsIds].filter((id) => pythonIds.has(id)).length;
  return {
    id: entry.id,
    language: entry.language,
    query: entry.query,
    python: pythonIds.size,
    ts: tsIds.size,
    intersection,
    jaccard: Number(jaccard(pythonIds, tsIds).toFixed(4)),
  };
});

function summary(language: "zh" | "en" | "all") {
  const subset = language === "all" ? rows : rows.filter((row) => row.language === language);
  const values = subset.map((row) => row.jaccard).sort((a, b) => a - b);
  const mean = values.reduce((sum, value) => sum + value, 0) / Math.max(1, values.length);
  return {
    queries: subset.length,
    meanJaccard: Number(mean.toFixed(4)),
    p50: values[Math.floor(values.length * 0.5)] ?? 0,
    p10: values[Math.floor(values.length * 0.1)] ?? 0,
    min: values[0] ?? 0,
    max: values[values.length - 1] ?? 0,
    zeroOverlap: subset.filter((row) => row.intersection === 0).length,
  };
}

const report = {
  corpus,
  queries: rows.length,
  overall: summary("all"),
  byLanguage: { zh: summary("zh"), en: summary("en") },
  worst: [...rows].sort((a, b) => a.jaccard - b.jaccard).slice(0, 12),
  rows,
};

console.log(JSON.stringify(report, null, 2));
index.close();
