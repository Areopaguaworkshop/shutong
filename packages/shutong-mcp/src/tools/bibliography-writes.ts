import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { paperDir, sourcePaper, writePaper } from "./paper-store.ts";

class WriteError extends Error {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

function validateEntries(entries: unknown): Array<Record<string, any>> {
  if (!Array.isArray(entries)) {
    throw new WriteError("invalid_bibliography", "Bibliography entries must be a list.");
  }
  for (const entry of entries) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry) || typeof entry.id !== "string" || !entry.id.trim()) {
      throw new WriteError("invalid_bibliography", "Each bibliography entry needs a stable non-empty id.");
    }
  }
  return entries as Array<Record<string, any>>;
}

function writeBibliographyArtifacts(sourceId: string, entries: Array<Record<string, any>>): void {
  const directory = path.join(paperDir(sourceId), "bibliography");
  mkdirSync(directory, { recursive: true });
  writeFileSync(path.join(directory, "shortlist.json"), `${JSON.stringify(entries, null, 2)}\n`, "utf8");
  const lines = ["# Bibliography shortlist", ""];
  for (const entry of entries) {
    const title = entry.title || entry.id;
    const annotation = entry.annotation || entry.rationale || "";
    lines.push(
      `## ${title}`,
      `- ID: \`${entry.id}\``,
      `- Proposed role: ${entry.role ?? "unknown"}`,
      `- Annotation: ${annotation}`,
      "",
    );
  }
  writeFileSync(path.join(directory, "shortlist.md"), lines.join("\n"), "utf8");
}

export async function handleBibliographyGroup(args: {
  action?: string;
  paper_id?: string;
  entries?: unknown;
  scope?: string;
  format?: string;
  content?: string;
  decision?: string;
  reason?: string;
}): Promise<Record<string, unknown>> {
  try {
    if (!args.paper_id) {
      return { status: "error", error_code: "invalid_input", message: "paper_id is required." };
    }
    const { paper, sourceId, sourcePaper: manifest } = sourcePaper(args.paper_id);

    if (args.action === "set") {
      const entries = validateEntries(args.entries ?? []);
      manifest.bibliography = { status: "draft", entries };
      writePaper(sourceId, manifest);
      writeBibliographyArtifacts(sourceId, entries);
      return { status: "needs_approval", paper_id: paper.id, source_workspace_id: sourceId, entry_count: entries.length };
    }

    if (args.action === "update") {
      const scope = args.scope;
      if (!["contextual", "opposing", "critical"].includes(String(scope))) {
        throw new WriteError("invalid_bibliography_scope", "Updates must be contextual, opposing, or critical.");
      }
      const additions = validateEntries(args.entries ?? []);
      const existing = new Map<string, Record<string, any>>();
      for (const entry of manifest.bibliography?.entries ?? []) {
        if (entry && typeof entry.id === "string") existing.set(entry.id, entry);
      }
      for (const entry of additions) existing.set(entry.id, { ...entry, scope });
      const entries = [...existing.values()];
      manifest.bibliography = { status: "draft", entries };
      writePaper(sourceId, manifest);
      writeBibliographyArtifacts(sourceId, entries);
      return {
        status: "needs_approval",
        paper_id: paper.id,
        source_workspace_id: sourceId,
        entry_count: entries.length,
        scope,
      };
    }

    if (args.action === "import") {
      const kind = args.format;
      if (!["bibtex", "csl-json"].includes(String(kind))) {
        throw new WriteError("invalid_bibliography_format", "Bibliography imports must be BibTeX or CSL-JSON.");
      }
      if (typeof args.content !== "string" || !args.content.trim()) {
        throw new WriteError("empty_bibliography_import", "A bibliography import cannot be empty.");
      }
      const suffix = kind === "bibtex" ? "bib" : "json";
      const importPath = path.join(paperDir(sourceId), "imports", `bibliography.${suffix}`);
      mkdirSync(path.dirname(importPath), { recursive: true });
      writeFileSync(importPath, args.content, "utf8");
      return { status: "ok", paper_id: paper.id, format: kind, path: importPath };
    }

    if (args.action === "approve") {
      const bibliography = manifest.bibliography ?? {};
      if (!Array.isArray(bibliography.entries) || bibliography.entries.length === 0) {
        throw new WriteError("empty_bibliography", "Save bibliography entries before approval.");
      }
      const decision = args.decision ?? "approve";
      if (!["approve", "narrow", "expand", "reject", "correct-classification"].includes(decision)) {
        throw new WriteError(
          "invalid_bibliography_decision",
          "Choose approve, narrow, expand, reject, or correct-classification.",
        );
      }
      bibliography.status =
        decision === "approve" ? "approved" : decision === "reject" ? "rejected" : "revision_requested";
      manifest.bibliography = bibliography;
      const auditPath = path.join(paperDir(sourceId), "audits", "bibliography-decisions.jsonl");
      mkdirSync(path.dirname(auditPath), { recursive: true });
      writeFileSync(
        auditPath,
        `${JSON.stringify({ decision, reason: String(args.reason ?? "").trim() })}\n`,
        { encoding: "utf8", flag: "a" },
      );
      writePaper(sourceId, manifest);
      return {
        status: decision === "approve" ? "ok" : "needs_revision",
        paper_id: paper.id,
        decision,
        entry_count: bibliography.entries.length,
      };
    }

    return {
      status: "error",
      error_code: "invalid_action",
      message: `Unknown bibliography action: ${args.action ?? ""}`,
    };
  } catch (error) {
    const failure = error as WriteError;
    return {
      status: "error",
      error_code: failure.code ?? "bibliography_error",
      message: failure.message,
    };
  }
}
