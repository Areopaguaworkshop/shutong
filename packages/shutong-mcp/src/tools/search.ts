import { getSearchIndex } from "./context.ts";

export interface SearchArgs {
  query?: string;
  pattern?: string;
  mode?: "keyword" | "regex";
  field?: string;
  top_k?: number;
  paper_id?: string;
  library_wide?: boolean;
}

export async function handleSearch(args: SearchArgs): Promise<Record<string, unknown>> {
  const index = await getSearchIndex();
  const mode = args.mode ?? "keyword";
  const limit = Math.max(1, Math.min(200, Number(args.top_k ?? 20) || 20));

  if (args.paper_id) {
    return {
      status: "error",
      error_code: "not_implemented",
      message: "Paper-scoped search is deferred until the paper state slice lands.",
      next_action: "Omit paper_id for library-wide search.",
    };
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
    const results = index.regexSearch(pattern, { limit });
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
  const results = index.search(query, { limit });
  return {
    status: "ok",
    query,
    retrieval_method: "bm25",
    total_results: results.length,
    results,
  };
}
