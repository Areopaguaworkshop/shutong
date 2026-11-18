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
