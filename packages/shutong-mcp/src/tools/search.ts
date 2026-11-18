import { searchPassages } from "./passage-search.ts";
import { currentPaperId, sourcePaper, StoreError } from "./paper-store.ts";
import { getSearchIndex, errorPayload } from "./context.ts";

export interface SearchArgs {
  query?: string;
  pattern?: string;
  mode?: "keyword" | "regex" | "passages";
  field?: string;
  top_k?: number;
  paper_id?: string;
  library_wide?: boolean;
  source_ids?: string[];
  intent?: "topic" | "quotation" | "parallel";
  seed?: { source_id: string; node_id: string };
}

export async function handleSearch(args: SearchArgs): Promise<Record<string, unknown>> {
  const index = await getSearchIndex();
  const mode = args.mode ?? "keyword";
  const limit = Math.max(1, Math.min(200, Number(args.top_k ?? 20) || 20));

  if (!["keyword", "regex", "passages"].includes(mode)) {
    return errorPayload("invalid_input", "Choose keyword, regex or passages.");
  }
  if (args.paper_id !== undefined && !args.paper_id) {
    return errorPayload("invalid_paper_id", "paper_id must be non-empty.");
  }
  const paperId = args.paper_id ?? (args.library_wide ? null : currentPaperId());
  let sourceIds = args.source_ids;
  if (args.source_ids !== undefined &&
      (!Array.isArray(args.source_ids) || args.source_ids.some((id) => typeof id !== "string" || !id))) {
    return errorPayload("invalid_input", "source_ids must contain non-empty source IDs.");
  }
  try {
    if (paperId) {
      const manifest = sourcePaper(paperId).sourcePaper;
      const allowed = (manifest.sources ?? []).map((source: { source_id: string }) => source.source_id);
      sourceIds = sourceIds === undefined ? allowed : sourceIds.filter((id) => allowed.includes(id));
    }
  } catch (error) {
    if (error instanceof StoreError) return errorPayload(error.code, error.message);
    throw error;
  }
  sourceIds = sourceIds === undefined ? undefined : [...new Set(sourceIds)];
  if (mode === "passages") {
    return searchPassages(index, args, { limit, sourceIds });
  }

  if (mode === "regex") {
    const pattern = args.pattern;
    if (!pattern) {
      return {
        status: "error",
        error_code: "invalid_input",
        message: "pattern is required when mode=regex",
      };
    }
    if (args.field && args.field !== "text") {
      return {
        status: "error",
        error_code: "invalid_input",
        message: "mode=regex only supports field=text",
      };
    }
    const results = index.regexSearch(pattern, { limit, sourceIds });
    return {
      status: "ok",
      query: pattern,
      retrieval_method: "regex",
      total_results: results.length,
      results,
    };
  }

  const query = args.query;
  if (!query) {
    return {
      status: "error",
      error_code: "invalid_input",
      message: "query is required when mode=keyword",
    };
  }
  if (args.field && args.field !== "text") {
    return {
      status: "error",
      error_code: "not_implemented",
      message: `field=${args.field} is deferred; only full-text search is implemented.`,
    };
  }
  const results = index.search(query, { limit, sourceIds });
  return {
    status: "ok",
    query,
    retrieval_method: "bm25",
    total_results: results.length,
    results,
  };
}
