import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { activePaperId, projectRoot } from "./paths.ts";
import { StoreError, usePaper } from "./paper-store.ts";
import { getSearchIndex, runtimeConfig } from "./context.ts";
import { corpusStatus } from "./corpus.ts";
import { handleStateSnapshot } from "./state.ts";
import { handleVerify } from "./verify.ts";

const PAPER_ID_RE = /^[a-z0-9][a-z0-9-]{0,62}$/;

export async function handleStatus(): Promise<Record<string, unknown>> {
  const corpus = await corpusStatus();
  const integrity = await handleVerify({ mode: "all" });
  const researchState = await handleStateSnapshot();
  return {
    corpus,
    integrity: {
      documents_checked: Array.isArray((integrity as any).documents)
        ? (integrity as any).documents.length
        : 0,
      failures: Number((integrity as any).failures ?? 0),
    },
    research_state: researchState,
  };
}

export async function handlePaperUse(args: {
  paper_id?: string;
  confirmed?: boolean;
}): Promise<Record<string, unknown>> {
  if (!args.paper_id) {
    return { status: "error", error_code: "invalid_input", message: "paper_id is required" };
  }
  try {
    return usePaper(args.paper_id, args.confirmed === true);
  } catch (error) {
    const failure = error as StoreError;
    return {
      status: "error",
      error_code: failure.code ?? "paper_error",
      message: failure.message,
    };
  }
}

export async function handlePaperStatus(args: {
  paper_id?: string;
}): Promise<Record<string, unknown>> {
  const cfg = runtimeConfig();
  const paperId = args.paper_id ?? activePaperId(cfg.corpusRoot);
  if (!paperId) return { status: "no_active_paper" };
  if (!PAPER_ID_RE.test(paperId)) {
    return {
      status: "error",
      error_code: "invalid_paper_id",
      message: "Paper IDs use lowercase letters, numbers, and hyphens.",
    };
  }

  // Touch the index so the server has a consistent runtime before paper reads.
  await getSearchIndex();
  const active = activePaperId(cfg.corpusRoot);
  const file = path.join(projectRoot(cfg.corpusRoot), "papers", paperId, "paper.json");
  if (!existsSync(file)) {
    return {
      status: "error",
      error_code: "paper_not_found",
      message: `Paper not found: ${paperId}`,
      next_action: "Create it with shutong paper create.",
    };
  }
  try {
    return {
      status: "ok",
      paper: JSON.parse(readFileSync(file, "utf8")),
      active: paperId === active,
    };
  } catch (error) {
    return {
      status: "error",
      error_code: "paper_manifest_invalid",
      message: (error as Error).message,
    };
  }
}
