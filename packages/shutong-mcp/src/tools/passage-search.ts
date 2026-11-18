import { execFile } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import type { SearchIndex, SearchOptions } from "../search/index.ts";
import { renderChicago } from "./citation.ts";
import { errorPayload, runtimeConfig } from "./context.ts";
import type { SearchArgs } from "./search.ts";

const run = promisify(execFile);
const worker = fileURLToPath(new URL("../../scripts/retrieve.py", import.meta.url));

interface Passage {
  id: number;
  source_id: string;
  node_id: string;
  page: number | null;
  para: number | null;
  text: string;
  sha256: string | null;
}

interface Match {
  id: number;
  start?: number;
  end?: number;
  seed_start?: number;
  seed_end?: number;
  score?: number;
}

async function externalMatches(
  method: "passim" | "bge-m3", passages: Passage[], query: string, limit: number,
): Promise<Match[]> {
  const directory = await mkdtemp(path.join(tmpdir(), "shutong-search-"));
  try {
    const input = path.join(directory, "input.json");
    const output = path.join(directory, "matches.json");
    await writeFile(input, JSON.stringify({ query, passages, limit }), { mode: 0o600 });
    await run(process.env.SHUTONG_RETRIEVAL_PYTHON || "python3",
      [worker, method, input, output, path.join(runtimeConfig().storageDir, "embedding-cache.sqlite")],
      { timeout: 300_000, cwd: directory });
    return JSON.parse(await readFile(output, "utf8")) as Match[];
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

function span(text: string, start: number, end: number) {
  return { start, end, text: text.slice(start, end) };
}

export async function searchPassages(index: SearchIndex, args: SearchArgs, options: SearchOptions) {
  const { sourceIds, limit = 20 } = options;
  const intent = args.intent ?? (args.seed ? "parallel" : "topic");
  if (!["topic", "quotation", "parallel"].includes(intent)) {
    return errorPayload("invalid_input", "Choose topic, quotation or parallel.");
  }
  const seedRef = args.seed;
  if (seedRef && (!seedRef.source_id || !seedRef.node_id || intent !== "parallel")) {
    return errorPayload("invalid_input", "A parallel seed requires source_id and node_id.");
  }
  const candidateLimit = Math.min(600, limit * 3);
  const where = sourceIds === undefined ? "" : "WHERE source_id IN (SELECT value FROM json_each(?))";
  const passages = index.db.prepare(
    "SELECT id, source_id, node_id, page, para, text, sha256 FROM nodes " + where + " ORDER BY id",
  ).all(...(sourceIds === undefined ? [] : [JSON.stringify(sourceIds)])) as unknown as Passage[];
  const seed = seedRef && passages.find((row) =>
    row.source_id === seedRef.source_id && row.node_id === seedRef.node_id);
  if (seedRef && !seed) return errorPayload("seed_not_found", "Seed passage is absent from the search scope.");
  const query = seed?.text ?? args.query?.trim();
  if (!query || query.length > 20_000) {
    return errorPayload("invalid_input", "Provide a question or passage of up to 20,000 characters.");
  }

  const byId = new Map(passages.map((row) => [row.id, row]));
  const positions = new Map(passages.map((row, offset) => [row.id, offset]));
  const byNode = new Map(passages.map((row) => [JSON.stringify([row.source_id, row.node_id]), row.id]));
  const sources = new Map((index.db.prepare("SELECT id, csl_json FROM sources").all() as
    Array<{ id: string; csl_json: string }>).map((row) => [row.id, JSON.parse(row.csl_json)]));
  const lists: Array<[string, Match[]]> = [];
  const warnings: string[] = [];
  if (intent === "topic") {
    const lexical = index.search(query, { sourceIds, limit: candidateLimit }).flatMap((hit) => {
      const id = byNode.get(JSON.stringify([hit.source_id, hit.node_id]));
      return id === undefined ? [] : [{ id, score: hit.score }];
    });
    lists.push(["bm25", lexical]);
  } else {
    const exact: Match[] = [];
    for (const row of passages) {
      const offset = row.text.indexOf(query);
      if (row.id !== seed?.id && offset >= 0) {
        exact.push({ id: row.id, start: offset, end: offset + query.length, seed_start: 0, seed_end: query.length });
        if (exact.length >= candidateLimit) break;
      }
    }
    lists.push(["exact", exact]);
  }

  const jobs: Array<{ method: "passim" | "bge-m3"; promise: Promise<Match[]> }> = [];
  if (passages.length && intent !== "topic") {
    jobs.push({ method: "passim", promise: externalMatches("passim", passages.filter((row) => row.id !== seed?.id), query, candidateLimit) });
  }
  if (passages.length && intent === "topic") {
    if (process.env.SHUTONG_BGE_MODEL) {
      jobs.push({ method: "bge-m3", promise: externalMatches("bge-m3", passages, query, candidateLimit) });
    } else {
      warnings.push("Set SHUTONG_BGE_MODEL to enable semantic retrieval.");
    }
  }
  const outcomes = await Promise.allSettled(jobs.map((job) => job.promise));
  outcomes.forEach((outcome, index) => {
    const { method } = jobs[index];
    if (outcome.status === "fulfilled") lists.push([method, outcome.value]);
    else warnings.push(`${method} unavailable. Check the optional retrieval dependencies and timeout.`);
  });

  const ranked = new Map<number, { score: number; exact: boolean; matches: object[] }>();
  for (const [method, matches] of lists) {
    const seen = new Set<number>();
    for (const [rank, match] of matches.entries()) {
      const row = byId.get(match.id);
      if (!row || row.id === seed?.id || seen.has(row.id)) continue;
      seen.add(row.id);
      const hit = ranked.get(row.id) ?? { score: 0, exact: false, matches: [] };
      hit.score += 1 / (60 + rank + 1);
      hit.exact ||= method === "exact";
      hit.matches.push({
        method,
        score: match.score,
        passage_span: match.start !== undefined && match.end !== undefined
          ? span(row.text, match.start, match.end) : undefined,
        seed_span: match.seed_start !== undefined && match.seed_end !== undefined
          ? span(query, match.seed_start, match.seed_end) : undefined,
      });
      ranked.set(row.id, hit);
    }
  }
  const cite = (row: Passage) => {
    const { id, ...passage } = row;
    const csl = sources.get(row.source_id) ?? {};
    const locator = row.page && row.page > 0 ? String(row.page) : row.para && row.para > 0 ? `para. ${row.para}` : null;
    const offset = positions.get(id)!;
    const before = passages[offset - 1];
    const after = passages[offset + 1];
    const context = {
      before: before?.source_id === row.source_id ? before.text.slice(-240) : "",
      after: after?.source_id === row.source_id ? after.text.slice(0, 240) : "",
    };
    return { ...passage, locator, context, csl, citation: renderChicago(csl, locator ?? "") };
  };
  const results = [...ranked].sort(([a, left], [b, right]) =>
    Number(right.exact) - Number(left.exact) || right.score - left.score || a - b,
  ).slice(0, limit).map(([id, hit]) => ({ ...cite(byId.get(id)!), score: hit.score, matches: hit.matches }));
  return {
    status: "ok", query, intent, seed: seed ? cite(seed) : null,
    retrieval_methods: lists.map(([method]) => method), warnings, total_results: results.length, results,
  };
}
