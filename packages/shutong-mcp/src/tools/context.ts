import { loadRuntimeConfig, type RuntimeConfig } from "../config.ts";
import { SearchIndex } from "../search/index.ts";

let config: RuntimeConfig | null = null;
let indexPromise: Promise<SearchIndex> | null = null;

export function runtimeConfig(): RuntimeConfig {
  config ??= loadRuntimeConfig();
  return config;
}

/**
 * Build the FTS5 index on first tool use, not during MCP initialization.
 * The factory passed to serveStdio may run twice; this keeps handshakes fast.
 */
export async function getSearchIndex(): Promise<SearchIndex> {
  if (indexPromise) return indexPromise;
  indexPromise = (async () => {
    const cfg = runtimeConfig();
    const index = new SearchIndex(cfg.dbPath);
    if (process.env.SHUTONG_SKIP_INDEX !== "1") {
      index.indexCorpus(cfg.corpusRoot, { reset: true });
    }
    return index;
  })();
  try {
    return await indexPromise;
  } catch (error) {
    indexPromise = null;
    throw error;
  }
}

export function errorPayload(
  code: string,
  message: string,
  nextAction = "",
): Record<string, unknown> {
  return { status: "error", error_code: code, message, next_action: nextAction };
}
