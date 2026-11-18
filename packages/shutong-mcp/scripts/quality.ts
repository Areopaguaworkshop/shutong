import { readdirSync, readFileSync, existsSync, rmSync } from "node:fs";
import path from "node:path";
import { buildMerkleTree } from "../src/contract/hash.ts";
import { SearchIndex } from "../src/search/index.ts";
import { queryTokens } from "../src/search/tokenize.ts";
import { IMPLEMENTED_TOOLS } from "../src/mcp/registry.ts";

interface Label {
  id: string;
  query: string;
  expected: string[];
}

interface Baseline {
  id: string;
  language: "zh" | "en";
  query: string;
  hits: Array<{ node_id: string | null; source_id: string | null }>;
}

const packageRoot = path.resolve(import.meta.dirname, "..");
const corpus = path.resolve(process.env.SHUTONG_CORPUS ?? path.join(packageRoot, "../../corpus"));
const dbPath = path.join(packageRoot, "../../.tmp/shutong-quality.sqlite");
if (existsSync(dbPath)) rmSync(dbPath);
const index = new SearchIndex(dbPath);
index.indexCorpus(corpus, { reset: true });

const labels = JSON.parse(
  readFileSync(path.join(packageRoot, "test/fixtures/chinese-relevance.json"), "utf8"),
) as Label[];
const baseline = JSON.parse(
  readFileSync(path.join(packageRoot, "test/fixtures/bm25-baseline.json"), "utf8"),
) as Baseline[];

function jaccard(left: Set<string>, right: Set<string>): number {
  if (left.size === 0 && right.size === 0) return 1;
  let intersection = 0;
  for (const value of left) if (right.has(value)) intersection += 1;
  return intersection / (left.size + right.size - intersection);
}

const chineseRows = labels.map((label) => {
  const hits = index.search(label.query, { limit: 10 });
  const actual = new Set(hits.map((hit) => hit.source_id));
  const expected = new Set(label.expected);
  const found = [...expected].filter((id) => actual.has(id));
  return {
    id: label.id,
    query: label.query,
    hit: found.length > 0,
    recall: found.length / expected.size,
    found,
  };
});
const zhHitRate = chineseRows.filter((row) => row.hit).length / chineseRows.length;
const zhMeanRecall = chineseRows.reduce((sum, row) => sum + row.recall, 0) / chineseRows.length;

const english = baseline.filter((entry) => entry.language === "en");
const englishRows = english.map((entry) => {
  const python = new Set(entry.hits.map((hit) => hit.node_id).filter((id): id is string => Boolean(id)));
  const ts = new Set(index.search(entry.query, { limit: 10 }).map((hit) => hit.node_id));
  return { id: entry.id, query: entry.query, jaccard: jaccard(python, ts) };
});
const enValues = englishRows.map((row) => row.jaccard).sort((a, b) => a - b);
const enP50 = enValues[Math.floor(enValues.length * 0.5)] ?? 0;

const { Jieba } = (await import("@node-rs/jieba")) as any;
const { dict } = (await import("@node-rs/jieba/dict.js")) as any;
const jieba = Jieba.withDict(dict);
const jiebaRows = labels.map((label) => {
  const intl = new Set(queryTokens(label.query));
  const jiebaTokens = new Set(
    (jieba.cut(label.query) as string[])
      .map((token) => token.normalize("NFC").toLowerCase())
      .filter((token) => /[\p{L}\p{N}]/u.test(token)),
  );
  return { query: label.query, overlap: jaccard(intl, jiebaTokens) };
});
const jiebaMean = jiebaRows.reduce((sum, row) => sum + row.overlap, 0) / jiebaRows.length;

const definitionNames = JSON.parse(
  readFileSync(path.join(packageRoot, "tools.generated.json"), "utf8"),
).map((tool: any) => tool.name).sort();
const implementedNames = [...IMPLEMENTED_TOOLS].sort();
const toolsExact = JSON.stringify(definitionNames) === JSON.stringify(implementedNames);

let merkleRoots = 0;
let merkleMismatches = 0;
for (const entry of readdirSync(corpus, { withFileTypes: true })) {
  if (!entry.isDirectory()) continue;
  const file = path.join(corpus, entry.name, "merkle.json");
  if (!existsSync(file)) continue;
  const merkle = JSON.parse(readFileSync(file, "utf8"));
  if (!Array.isArray(merkle.levels?.[0])) continue;
  merkleRoots += 1;
  if (buildMerkleTree(merkle.levels[0]).root !== merkle.root) merkleMismatches += 1;
}

const gates = {
  chineseHitRate: zhHitRate >= 0.8,
  chineseMeanRecall: zhMeanRecall >= 0.8,
  englishP50: enP50 >= 0.8,
  toolsExact,
  merkleRoots: merkleRoots === 280 && merkleMismatches === 0,
  jiebaTokenOverlap: jiebaMean >= 0.6,
};

const report = {
  ok: Object.values(gates).every(Boolean),
  gates,
  chinese: { queries: labels.length, hitRate: zhHitRate, meanRecall: zhMeanRecall, rows: chineseRows },
  english: { queries: english.length, p50: enP50, rows: englishRows },
  jieba: { meanTokenOverlap: jiebaMean, rows: jiebaRows },
  tools: { definitions: definitionNames.length, implemented: implementedNames.length, exact: toolsExact },
  merkle: { roots: merkleRoots, mismatches: merkleMismatches },
  residualGaps: [
    "custom bibliography adapters (catalogue, OAI-PMH, publisher) are still deferred",
    "Intl.Segmenter remains the production tokenizer; jieba is comparison-only",
    "analysis uses JS UTF-16 offsets; astral Han spans may differ from Python",
  ],
};

console.log(JSON.stringify(report, null, 2));
index.close();
process.exitCode = report.ok ? 0 : 1;
