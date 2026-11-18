import { existsSync } from "node:fs";
import path from "node:path";
import { getSearchIndex, runtimeConfig } from "./context.ts";

export interface CorpusArgs {
  action?: string;
}

function maxIngestionTime(rows: Array<{ csl_json: string }>): string | null {
  let latest: string | null = null;
  for (const row of rows) {
    try {
      const value = JSON.parse(row.csl_json)?.ingestion_timestamp;
      if (typeof value === "string" && (!latest || value > latest)) latest = value;
    } catch {
      // ignore malformed legacy rows
    }
  }
  return latest;
}

export async function corpusStatus(): Promise<Record<string, unknown>> {
  const index = await getSearchIndex();
  const cfg = runtimeConfig();
  const rows = index.db.prepare("SELECT id, folder, csl_json FROM sources").all() as Array<{
    id: string;
    folder: string;
    csl_json: string;
  }>;
  const nodeRow = index.db.prepare("SELECT count(*) AS c FROM nodes").get() as { c: number };
  let withTrees = 0;
  for (const row of rows) {
    if (existsSync(path.join(cfg.corpusRoot, row.folder, "merkle.json"))) withTrees += 1;
  }
  return {
    status: "ok",
    document_count: rows.length,
    total_nodes: Number(nodeRow.c),
    last_ingestion_time: maxIngestionTime(rows),
    merkle_health: {
      documents_with_trees: withTrees,
      documents_missing_trees: rows.length - withTrees,
    },
  };
}

export async function corpusTree(): Promise<Record<string, unknown>> {
  const index = await getSearchIndex();
  const cfg = runtimeConfig();
  const rows = index.db
    .prepare(
      `SELECT s.id AS source_id, s.folder, s.title, s.author_text, s.year,
              (SELECT count(*) FROM nodes n WHERE n.source_id = s.id) AS node_count
       FROM sources s ORDER BY s.title, s.id`,
    )
    .all() as Array<{
    source_id: string;
    folder: string;
    title: string;
    author_text: string | null;
    year: number | null;
    node_count: number;
  }>;
  return {
    status: "ok",
    documents: rows.map((row) => ({
      source_id: row.source_id,
      title: row.title,
      author: row.author_text ?? "",
      year: row.year == null ? "" : String(row.year),
      node_count: Number(row.node_count),
      document_path: path.join(cfg.corpusRoot, row.folder),
    })),
  };
}

export async function handleCorpus(args: CorpusArgs): Promise<Record<string, unknown>> {
  const action = args.action ?? "status";
  if (action === "status") return corpusStatus();
  if (action === "tree") return corpusTree();
  return {
    status: "error",
    error_code: "invalid_action",
    message: `Unknown corpus action: ${action}`,
    next_action: "Use action=status or action=tree.",
  };
}
