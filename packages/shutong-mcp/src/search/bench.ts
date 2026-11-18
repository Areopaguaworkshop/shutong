import { readFileSync } from "node:fs";
import { searchPassages } from "../tools/passage-search.ts";
import path from "node:path";
import { SearchIndex } from "./index.ts";

const corpus = path.resolve(
  process.env.SHUTONG_CORPUS ?? path.join(import.meta.dirname, "../../../../corpus"),
);
const dbPath = path.resolve(
  process.env.SHUTONG_INDEX_DB ?? path.join(import.meta.dirname, "../../../../.tmp/shutong-search.sqlite"),
);

const queries = process.argv.slice(2);
const defaultQueries = [
  "中国",
  "自由意志",
  "尼西亚",
  "theology",
  "袁永甲",
  "教会 传统",
  "神学 历史",
  "justification",
];

const started = performance.now();
const index = new SearchIndex(dbPath);
const stats = index.indexCorpus(corpus, { reset: true });
const buildMs = performance.now() - started;

console.log(
  JSON.stringify(
    {
      corpus,
      dbPath,
      buildMs: Math.round(buildMs),
      documents: stats.documents,
      nodes: stats.nodes,
      dbMB: Number((stats.dbBytes / 1e6).toFixed(1)),
      schemaVersion: stats.schemaVersion,
    },
    null,
    2,
  ),
);

const evaluationFile = process.env.SHUTONG_SEARCH_EVALUATION;
if (evaluationFile) {
  const cases: Array<{
    query: string;
    intent?: "topic" | "quotation" | "parallel";
    language: string;
    relevant: Array<{ source_id: string; node_id: string; span?: string }>;
  }> = JSON.parse(readFileSync(evaluationFile, "utf8"));
  for (const { query, intent = "topic", language, relevant } of cases) {
    const key = (row: { source_id: string; node_id: string }) => JSON.stringify([row.source_id, row.node_id]);
    const expected = new Map(relevant.map((row) => [key(row), row]));
    const measures = (hits: Array<{ source_id: string; node_id: string }>) => {
      const retrieved = hits.filter((hit) => expected.has(key(hit))).length;
      const dcg = hits.reduce((sum, hit, rank) =>
        sum + (expected.has(key(hit)) ? 1 / Math.log2(rank + 2) : 0), 0);
      const ideal = [...Array(Math.min(10, expected.size)).keys()]
        .reduce((sum, rank) => sum + 1 / Math.log2(rank + 2), 0);
      return { recall_at_10: expected.size ? retrieved / expected.size : null,
        ndcg_at_10: ideal ? dcg / ideal : null, returned: hits.length };
    };
    const start = performance.now();
    const baseline = index.search(query, { limit: 10 });
    const baselineMs = performance.now() - start;
    const retrievedAt = performance.now();
    const result = await searchPassages(index, { query, intent }, { limit: 10 });
    if (result.status !== "ok" || !("results" in result) || !Array.isArray(result.results)) {
      throw new Error(JSON.stringify(result));
    }
    const matchingSpans = result.results.filter((hit) => {
      const wanted = expected.get(key(hit))?.span;
      return wanted && hit.matches.some((match: { passage_span?: { text: string } }) =>
        match.passage_span?.text === wanted);
    }).length;
    console.log(JSON.stringify({ query, intent, language,
      baseline: { ...measures(baseline), ms: baselineMs },
      passages: { ...measures(result.results), ms: performance.now() - retrievedAt, matchingSpans },
      methods: result.retrieval_methods, warnings: result.warnings,
    }));
  }
}
for (const query of queries.length > 0 ? queries : defaultQueries) {
  const t0 = performance.now();
  const hits = index.search(query, { limit: 10 });
  const ms = performance.now() - t0;
  console.log(
    JSON.stringify({
      query,
      ms: Number(ms.toFixed(2)),
      hits: hits.length,
      top: hits.slice(0, 3).map((hit) => ({
        source_id: hit.source_id,
        page: hit.page,
        score: hit.score,
        text: hit.text.slice(0, 100),
      })),
    }),
  );
}

index.close();
