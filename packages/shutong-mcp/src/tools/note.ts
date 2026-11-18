import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { parseNote, loadVerifierReport, checkNoteAnalysis } from "./audit.ts";
import { nextId } from "./ids.ts";
import { paperDir, readPaper, sourcePaper } from "./paper-store.ts";
import { serializeNote } from "./python.ts";

const ID_RE = /^[a-z0-9][a-z0-9-]{0,62}$/;
const CONFIDENCE = new Set(["known", "probable", "speculative"]);

class NoteError extends Error {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

function notesDir(paperId: string): string {
  return path.join(paperDir(paperId), "notes");
}

function requiredText(args: Record<string, any>, key: string, message: string): string {
  const value = args[key];
  if (typeof value !== "string" || !value.trim()) throw new NoteError("invalid_note", message);
  return value.trim();
}

function noteBody(file: string): string {
  const text = readFileSync(file, "utf8");
  const end = text.indexOf("\n---\n", 3);
  if (end < 0) throw new NoteError("invalid_note_metadata", "Note frontmatter is not terminated.");
  return text.slice(end + 5);
}

export async function handleNote(args: {
  action?: string;
  paper_id?: string;
  note_id?: string;
  source_id?: string;
  locator?: string;
  claim?: string;
  evidence?: string;
  confidence?: string;
  tags?: string[];
  analysis_id?: string;
  query?: string;
  context?: number;
  verifier_report_id?: string;
  report_id?: string;
}): Promise<Record<string, unknown>> {
  try {
    if (!args.paper_id) {
      return { status: "error", error_code: "invalid_input", message: "paper_id is required." };
    }
    const { paper, sourcePaper: manifest } = sourcePaper(args.paper_id);
    const dir = notesDir(args.paper_id);

    if (args.action === "add") {
      const sourceId = String(args.source_id ?? "");
      const source = (manifest.sources ?? []).find((item: any) => item.source_id === sourceId);
      if (!source || source.ingested !== true) {
        throw new NoteError("source_not_ingested", "Notes require an approved, properly ingested paper source.");
      }
      const noteId = args.note_id ?? nextId(dir, "note-", ".md");
      if (!ID_RE.test(noteId)) {
        throw new NoteError("invalid_note_id", "Note IDs use lowercase letters, numbers, and hyphens.");
      }
      const file = path.join(dir, `${noteId}.md`);
      if (existsSync(file)) throw new NoteError("note_exists", `Note already exists: ${noteId}`);
      const locator = requiredText(args as any, "locator", "Notes require a corpus locator.");
      const claim = requiredText(args as any, "claim", "Notes require one atomic claim.");
      const evidence = requiredText(args as any, "evidence", "Notes require source evidence or a tight paraphrase.");
      if (!CONFIDENCE.has(String(args.confidence))) {
        throw new NoteError("invalid_note_confidence", "Note confidence must be known, probable, or speculative.");
      }
      const tags = args.tags;
      if (!Array.isArray(tags) || tags.length === 0 || tags.some((tag) => typeof tag !== "string" || !tag.trim())) {
        throw new NoteError("invalid_note_tags", "Notes require one or more non-empty tags.");
      }
      const metadata: Record<string, unknown> = {
        source_id: sourceId,
        locator,
        note_schema: "evidence-v1",
        confidence: args.confidence,
        tags,
      };
      if (args.analysis_id) metadata.analysis_id = args.analysis_id;
      metadata.verified = false;
      mkdirSync(dir, { recursive: true });
      writeFileSync(
        file,
        serializeNote(metadata, `\n## Claim\n\n${claim}\n\n## Evidence\n\n${evidence}\n`),
        "utf8",
      );
      return { status: "ok", paper_id: paper.id, note_id: noteId };
    }

    if (args.action === "search") {
      const query = String(args.query ?? "").trim();
      if (!query) throw new NoteError("empty_note_query", "Note search requires a keyword or phrase.");
      const radius = Math.max(20, Math.min(500, Number(args.context ?? 120) || 120));
      const matches: Array<Record<string, unknown>> = [];
      if (existsSync(dir)) {
        for (const file of readdirSync(dir).filter((name) => name.endsWith(".md")).sort()) {
          const text = readFileSync(path.join(dir, file), "utf8");
          const start = text.toLocaleLowerCase().indexOf(query.toLocaleLowerCase());
          if (start < 0) continue;
          let metadata: Record<string, any> = {};
          try {
            metadata = parseNote(path.join(dir, file), file.slice(0, -3));
          } catch {
            metadata = {};
          }
          const tags = metadata.tags;
          matches.push({
            note_id: file.slice(0, -3),
            source_id: metadata.source_id ?? "",
            locator: metadata.locator ?? "",
            confidence: metadata.confidence ?? "",
            tags: Array.isArray(tags) ? JSON.stringify(tags) : (tags ?? ""),
            snippet: text.slice(Math.max(0, start - radius), start + query.length + radius),
          });
        }
      }
      return { status: "ok", paper_id: args.paper_id, query, matches };
    }

    if (args.action === "verify") {
      const noteId = String(args.note_id ?? "");
      if (!ID_RE.test(noteId)) {
        throw new NoteError("invalid_note_id", "Note IDs use lowercase letters, numbers, and hyphens.");
      }
      const file = path.join(dir, `${noteId}.md`);
      const metadata = parseNote(file, noteId);
      const evidence = String(args.evidence ?? "").trim();
      let reportId = args.verifier_report_id ?? args.report_id;
      if (!reportId && ID_RE.test(evidence)) {
        const candidate = path.join(paperDir(args.paper_id), "audits", `${evidence}.json`);
        if (existsSync(candidate)) reportId = evidence;
      }
      if (!reportId) {
        throw new NoteError(
          "missing_verification_report",
          "Record a passing verifier report and pass its ID as evidence before verifying.",
        );
      }
      const report = loadVerifierReport(paperDir(args.paper_id), reportId);
      if (report.outcome !== "pass") {
        throw new NoteError("verifier_report_not_passing", `Verification requires a passing verifier report: ${reportId}`);
      }
      if ((report.scope ?? "paper") !== "paper" && report.scope !== `note:${noteId}`) {
        throw new NoteError(
          "report_scope_mismatch",
          `Verifier report ${reportId} is scoped to ${report.scope}, not note:${noteId}.`,
        );
      }
      if (!evidence) {
        throw new NoteError(
          "missing_verification_evidence",
          "Verified notes require a passing verifier report; pass its ID as evidence.",
        );
      }
      if (metadata.verified !== false) {
        throw new NoteError("invalid_note", `Note ${noteId} has no verifiable note metadata.`);
      }
      const analysisDigest = checkNoteAnalysis(metadata, paper.id, paperDir(args.paper_id));
      metadata.verified = true;
      metadata.verification = evidence;
      if (analysisDigest) metadata.analysis_review_sha256 = analysisDigest;
      metadata.verifier_report_id = reportId;
      const body = noteBody(file);
      writeFileSync(file, serializeNote(metadata, body), "utf8");
      return { status: "ok", paper_id: paper.id, note_id: noteId };
    }

    return {
      status: "error",
      error_code: "invalid_action",
      message: `Unknown note action: ${args.action ?? ""}`,
    };
  } catch (error) {
    const failure = error as NoteError;
    return {
      status: "error",
      error_code: failure.code ?? "note_error",
      message: failure.message,
    };
  }
}
