import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { runtimeConfig } from "./context.ts";
import { activePaperId, projectRoot } from "./paths.ts";

export const PAPER_ID_RE = /^[a-z0-9][a-z0-9-]{0,62}$/;

export class StoreError extends Error {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

export function paperDir(paperId: string): string {
  return path.join(projectRoot(runtimeConfig().corpusRoot), "papers", paperId);
}

export function paperPath(paperId: string): string {
  return path.join(paperDir(paperId), "paper.json");
}

export function readPaper(paperId: string): Record<string, any> {
  if (!PAPER_ID_RE.test(paperId)) {
    throw new StoreError("invalid_paper_id", "Paper IDs use lowercase letters, numbers, and hyphens.");
  }
  const file = paperPath(paperId);
  if (!existsSync(file)) {
    throw new StoreError("paper_not_found", `Paper not found: ${paperId}`);
  }
  try {
    return JSON.parse(readFileSync(file, "utf8"));
  } catch {
    throw new StoreError("paper_manifest_invalid", `Paper manifest is unreadable: ${paperId}`);
  }
}

export function writePaper(paperId: string, paper: Record<string, unknown>): void {
  const dir = paperDir(paperId);
  mkdirSync(dir, { recursive: true });
  writeFileSync(paperPath(paperId), `${JSON.stringify(paper, null, 2)}\n`, "utf8");
}

/** Return the paper and the shared source-library manifest a work points at. */
export function sourcePaper(paperId: string): {
  paper: Record<string, any>;
  sourceId: string;
  sourcePaper: Record<string, any>;
} {
  const paper = readPaper(paperId);
  const sourceId = paper.source_workspace_id ?? paperId;
  const sourceManifest = sourceId === paperId ? paper : readPaper(sourceId);
  return { paper, sourceId, sourcePaper: sourceManifest };
}

export function createPaper(args: {
  paper_id: string;
  title: string;
  question?: string;
  minimum_primary?: number;
  minimum_secondary?: number;
}): Record<string, unknown> {
  if (!PAPER_ID_RE.test(args.paper_id)) {
    throw new StoreError("invalid_paper_id", "Paper IDs use lowercase letters, numbers, and hyphens.");
  }
  const dir = paperDir(args.paper_id);
  if (existsSync(path.join(dir, "paper.json"))) {
    throw new StoreError("paper_exists", `Paper already exists: ${args.paper_id}`);
  }
  const paper = {
    id: args.paper_id,
    title: args.title,
    question: args.question ?? "",
    sources: [],
    bibliography: { status: "draft", entries: [] },
    ingestion: { mode: null, authorized_source_ids: [] },
    policy: {
      minimum_primary: args.minimum_primary ?? 1,
      minimum_secondary: args.minimum_secondary ?? 1,
    },
  };
  writePaper(args.paper_id, paper);
  for (const name of ["drafts", "notes", "claims", "audits", "imports", "bibliography", "contacts"]) {
    mkdirSync(path.join(dir, name), { recursive: true });
  }
  return { status: "ok", paper, path: path.join(dir, "paper.json") };
}

export function usePaper(paperId: string, confirmed: boolean): Record<string, unknown> {
  const paper = readPaper(paperId);
  if (paper.project_id && !confirmed) {
    throw new StoreError(
      "workspace_switch_needs_confirmation",
      "Activate a project work through the Workspace Planner after the scholar confirms the switch.",
    );
  }
  const active = path.join(projectRoot(runtimeConfig().corpusRoot), ".shutong", "active-paper");
  mkdirSync(path.dirname(active), { recursive: true });
  writeFileSync(active, `${paper.id}\n`, "utf8");
  return { status: "ok", paper_id: paper.id };
}

export function currentPaperId(): string | null {
  return activePaperId(runtimeConfig().corpusRoot);
}
