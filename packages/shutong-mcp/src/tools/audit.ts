import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, realpathSync } from "node:fs";
import path from "node:path";
import { parse as parseYaml } from "yaml";
import { pythonJsonDumpsSpaced, sha256Hex } from "../contract/hash.ts";
import { runtimeConfig } from "./context.ts";
import { activePaperId, projectRoot, readJsonFile } from "./paths.ts";

const ID_RE = /^[a-z0-9][a-z0-9-]{0,62}$/;

class AuditFailure extends Error {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

function noteDigest(file: string): string {
  return createHash("sha256").update(readFileSync(file)).digest("hex");
}

export function parseNote(file: string, noteId: string): Record<string, any> {
  if (!existsSync(file)) throw new AuditFailure("note_not_found", `Note not found: ${noteId}`);
  const text = readFileSync(file, "utf8");
  const lines = text.split(/\r?\n/);
  if (lines[0] !== "---") {
    throw new AuditFailure("invalid_note_metadata", "Notes require a YAML frontmatter block.");
  }
  const end = lines.indexOf("---", 1);
  if (end < 0) {
    throw new AuditFailure("invalid_note_metadata", "Note frontmatter is not terminated.");
  }
  let metadata: unknown;
  try {
    metadata = parseYaml(lines.slice(1, end).join("\n")) ?? {};
  } catch (error) {
    throw new AuditFailure("invalid_note_metadata", `Note frontmatter is not valid YAML: ${(error as Error).message}`);
  }
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
    throw new AuditFailure("invalid_note_metadata", "Note frontmatter must be a YAML mapping.");
  }
  return metadata as Record<string, any>;
}

export function loadVerifierReport(paperDir: string, reportId: unknown): Record<string, any> {
  if (typeof reportId !== "string" || !ID_RE.test(reportId)) {
    throw new AuditFailure("invalid_report_id", "Report IDs use lowercase letters, numbers, and hyphens.");
  }
  const file = path.join(paperDir, "audits", `${reportId}.json`);
  if (!existsSync(file)) {
    throw new AuditFailure("report_not_found", `Verifier report not found: ${reportId}`);
  }
  const report = readJsonFile(file);
  if (!report || typeof report !== "object" || Array.isArray(report)) {
    throw new AuditFailure("invalid_verifier_report", `Verifier report must be a JSON object: ${reportId}`);
  }
  return report;
}

export function checkNoteAnalysis(
  metadata: Record<string, any>,
  paperId: string,
  paperDir: string,
): string | null {
  const analysisId = metadata.analysis_id;
  if (analysisId === undefined || analysisId === null) return null;
  if (typeof analysisId !== "string" || !analysisId) {
    throw new AuditFailure("invalid_note_metadata", "A note analysis_id must be a non-empty string.");
  }
  const record = readJsonFile(path.join(paperDir, "analyses", `${analysisId}.json`));
  if (!record) throw new AuditFailure("analysis_not_found", "Analysis not found in this paper.");
  if (record.review?.outcome !== "pass") {
    throw new AuditFailure("analysis_not_verified", "Analysis-backed notes require a passing analysis review.");
  }
  const digest = sha256Hex(pythonJsonDumpsSpaced(record));
  const previous = metadata.analysis_review_sha256;
  if (previous !== undefined && previous !== null && previous !== digest) {
    throw new AuditFailure("stale_analysis_note", "Analysis changed after this note was verified.");
  }
  return digest;
}

export function validatedIngestion(corpusRoot: string, sourceId: string): string {  const registry = readJsonFile(path.join(projectRoot(corpusRoot), ".shutong", "source-registry.json"));
  const record = registry?.[sourceId];
  if (!record || typeof record !== "object") {
    throw new AuditFailure("ingestion_not_found", `No local ingestion record found for source: ${sourceId}`);
  }
  const rawPath = record.document_path;
  if (typeof rawPath !== "string" || !rawPath.trim()) {
    throw new AuditFailure("ingestion_not_found", `No local ingestion record found for source: ${sourceId}`);
  }
  const root = realpathSync(path.resolve(corpusRoot));
  let candidate = rawPath.startsWith("~")
    ? rawPath.replace(/^~/, process.env.HOME ?? "")
    : rawPath;
  if (!path.isAbsolute(candidate)) {
    const projectCandidate = path.join(projectRoot(corpusRoot), candidate);
    candidate = existsSync(projectCandidate) ? projectCandidate : path.join(root, candidate);
  }
  candidate = path.resolve(candidate);
  try {
    candidate = realpathSync(candidate);
  } catch {
    throw new AuditFailure("ingestion_stale", `The ingestion record for ${sourceId} cannot be resolved.`);
  }
  const relative = path.relative(root, candidate);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new AuditFailure("ingestion_outside_corpus", `The ingestion record for ${sourceId} points outside the corpus root.`);
  }
  for (const name of ["document.json", "merkle.json"]) {
    if (!existsSync(path.join(candidate, name))) {
      throw new AuditFailure("ingestion_stale", `The ingested document for ${sourceId} is missing ${name}.`);
    }
  }
  const document = readJsonFile(path.join(candidate, "document.json"));
  const merkle = readJsonFile(path.join(candidate, "merkle.json"));
  if (!document || typeof document !== "object" || !merkle || typeof merkle !== "object" || !merkle.root) {
    throw new AuditFailure("ingestion_stale", `The ingested document for ${sourceId} has no Merkle root.`);
  }
  return candidate;
}

export function verifyClaimEvidence(
  claim: Record<string, any>,
  notesDir: string,
  paperId: string,
  paperDir: string,
): void {
  const noteIds = claim.note_ids;
  const digests = claim.note_digests;
  if (!Array.isArray(noteIds) || noteIds.length === 0 || !digests || typeof digests !== "object") {
    throw new AuditFailure("missing_claim_evidence", "Claims require digest-bound verified note IDs.");
  }
  for (const noteId of noteIds) {
    if (typeof noteId !== "string" || !ID_RE.test(noteId)) {
      throw new AuditFailure("invalid_note_id", "Invalid claim note ID.");
    }
    const expected = digests[noteId];
    if (typeof expected !== "string" || !expected) {
      throw new AuditFailure("missing_claim_evidence", `Claim note lacks a recorded digest: ${noteId}`);
    }
    const notePath = path.join(notesDir, `${noteId}.md`);
    if (!existsSync(notePath)) {
      throw new AuditFailure("note_not_found", `Claim note is missing: ${noteId}`);
    }
    if (noteDigest(notePath) !== expected) {
      throw new AuditFailure("stale_claim_evidence", `Note changed after the claim was created: ${noteId}`);
    }
    const metadata = parseNote(notePath, noteId);
    if (metadata.verified !== true) {
      throw new AuditFailure("note_not_verified", `Claim evidence is not a verified note: ${noteId}`);
    }
    const reportId = metadata.verifier_report_id;
    if (!reportId) {
      throw new AuditFailure("missing_verification_report", `Claim note has no linked verifier report: ${noteId}`);
    }
    const report = loadVerifierReport(paperDir, reportId);
    if (report.outcome !== "pass") {
      throw new AuditFailure("verifier_report_not_passing", `Claim note has no passing verifier report: ${noteId}`);
    }
    if ((report.scope ?? "paper") !== "paper" && report.scope !== `note:${noteId}`) {
      throw new AuditFailure("report_scope_mismatch", `Verifier report ${reportId} does not cover note ${noteId}.`);
    }
    checkNoteAnalysis(metadata, paperId, paperDir);
  }
}

function blockingReports(paperDir: string): Array<Record<string, unknown>> {
  const auditsDir = path.join(paperDir, "audits");
  const overridden = new Set<string>();
  const overridesPath = path.join(auditsDir, "overrides.jsonl");
  if (existsSync(overridesPath)) {
    for (const line of readFileSync(overridesPath, "utf8").split("\n")) {
      try {
        const record = JSON.parse(line);
        if (record && typeof record.report_id === "string") overridden.add(record.report_id);
      } catch {
        // ignore malformed override lines
      }
    }
  }
  const blocking: Array<Record<string, unknown>> = [];
  if (!existsSync(auditsDir)) return blocking;
  for (const file of readdirSync(auditsDir).filter((name) => name.endsWith(".json")).sort()) {
    const reportId = file.slice(0, -5);
    const report = readJsonFile(path.join(auditsDir, file));
    if (!report) {
      blocking.push({ report_id: reportId, outcome: "unreadable" });
      continue;
    }
    if ((report.outcome === "fail" || report.outcome === "uncertain") && !overridden.has(reportId)) {
      blocking.push({ report_id: reportId, outcome: report.outcome });
    }
  }
  return blocking;
}

function missing(stage: string, extra: Record<string, unknown>): Record<string, unknown> {
  return { stage, ...extra };
}

function auditPaper(paperId: string, corpusRoot: string): Record<string, unknown> {
  const paperDir = path.join(projectRoot(corpusRoot), "papers", paperId);
  const manifest = readJsonFile(path.join(paperDir, "paper.json"));
  if (!manifest) {
    throw new AuditFailure("paper_not_found", `Paper not found: ${paperId}`);
  }
  const sourceId = manifest.source_workspace_id ?? paperId;
  const sourceManifest = sourceId === paperId
    ? manifest
    : readJsonFile(path.join(projectRoot(corpusRoot), "papers", sourceId, "paper.json"));
  if (!sourceManifest) {
    throw new AuditFailure("paper_not_found", `Source workspace not found: ${sourceId}`);
  }

  const missingItems: Array<Record<string, unknown>> = [];
  const validIngested = new Set<string>();
  for (const item of sourceManifest.sources ?? []) {
    if (item?.ingested !== true) continue;
    try {
      validatedIngestion(corpusRoot, item.source_id);
    } catch (error) {
      missingItems.push(
        missing("ingestion", {
          source_id: item.source_id ?? "",
          required: "surviving registry document with Merkle files",
          actual: (error as AuditFailure).code ?? "ingestion_error",
        }),
      );
      continue;
    }
    validIngested.add(item.source_id);
  }

  const roles = ["primary", "secondary", "unknown"];
  const counts: Record<string, number> = {};
  for (const role of roles) {
    counts[role] = (sourceManifest.sources ?? []).filter(
      (item: any) => item.role === role && validIngested.has(item.source_id),
    ).length;
  }
  const policy = manifest.policy ?? {};
  for (const [role, key] of [["primary", "minimum_primary"], ["secondary", "minimum_secondary"]] as const) {
    const required = Number(policy[key] ?? 1);
    if (counts[role] < required) {
      missingItems.push({ role, required, actual: counts[role] });
    }
  }
  if (sourceManifest.bibliography?.status !== "approved") {
    missingItems.push(
      missing("bibliography", {
        required: "approved",
        actual: sourceManifest.bibliography?.status ?? "missing",
      }),
    );
  }
  if (validIngested.size === 0) {
    missingItems.push(missing("ingestion", { required: "at least one valid ingested source", actual: 0 }));
  }

  const notesDir = path.join(paperDir, "notes");
  const validNotes = new Set<string>();
  if (existsSync(notesDir)) {
    for (const file of readdirSync(notesDir).filter((name) => name.endsWith(".md")).sort()) {
      const noteId = file.slice(0, -3);
      let metadata: Record<string, any>;
      try {
        metadata = parseNote(path.join(notesDir, file), noteId);
      } catch (error) {
        missingItems.push(
          missing("note_metadata", {
            note_id: noteId,
            required: "valid frontmatter",
            actual: (error as AuditFailure).code ?? "note_metadata_invalid",
          }),
        );
        continue;
      }
      try {
        checkNoteAnalysis(metadata, manifest.id, paperDir);
      } catch (error) {
        missingItems.push(
          missing("analysis", {
            note_id: noteId,
            required: "current passing analysis review",
            actual: (error as AuditFailure).code ?? "analysis_error",
          }),
        );
        continue;
      }
      if (metadata.verified !== true) continue;
      const reportId = metadata.verifier_report_id;
      if (!reportId) {
        missingItems.push(
          missing("verifier_report", {
            note_id: noteId,
            required: "linked passing verifier report",
            actual: "missing",
          }),
        );
        continue;
      }
      let report: Record<string, any>;
      try {
        report = loadVerifierReport(paperDir, reportId);
      } catch (error) {
        missingItems.push(
          missing("verifier_report", {
            note_id: noteId,
            required: "linked passing verifier report",
            actual: (error as AuditFailure).code ?? "report_error",
          }),
        );
        continue;
      }
      if (report.outcome !== "pass") {
        missingItems.push(
          missing("verifier_report", {
            note_id: noteId,
            required: "linked passing verifier report",
            actual: report.outcome,
          }),
        );
        continue;
      }
      if ((report.scope ?? "paper") !== "paper" && report.scope !== `note:${noteId}`) {
        missingItems.push(
          missing("verifier_report", {
            note_id: noteId,
            required: `scope paper or note:${noteId}`,
            actual: report.scope,
          }),
        );
        continue;
      }
      validNotes.add(noteId);
    }
  }
  if (validNotes.size === 0) {
    missingItems.push(
      missing("notes", {
        required: "at least one verified note with current note metadata",
        actual: 0,
      }),
    );
  }

  const claimsDir = path.join(paperDir, "claims");
  const validClaims = new Set<string>();
  if (existsSync(claimsDir)) {
    for (const file of readdirSync(claimsDir).filter((name) => name.endsWith(".json")).sort()) {
      const claimId = file.slice(0, -5);
      const claim = readJsonFile(path.join(claimsDir, file));
      if (!claim || typeof claim !== "object" || Array.isArray(claim)) {
        missingItems.push(
          missing("claim_metadata", {
            claim_id: claimId,
            required: "readable claim JSON",
            actual: "unreadable",
          }),
        );
        continue;
      }
      if (claim.verified !== true) continue;
      try {
        verifyClaimEvidence(claim, notesDir, manifest.id, paperDir);
      } catch (error) {
        missingItems.push(
          missing("claim_evidence", {
            claim_id: claimId,
            required: "note references and digests still match",
            actual: (error as AuditFailure).code ?? "claim_evidence_error",
          }),
        );
        continue;
      }
      const reportId = claim.verifier_report_id;
      if (!reportId) {
        missingItems.push(
          missing("verifier_report", {
            claim_id: claimId,
            required: "linked passing verifier report",
            actual: "missing",
          }),
        );
        continue;
      }
      let report: Record<string, any>;
      try {
        report = loadVerifierReport(paperDir, reportId);
      } catch (error) {
        missingItems.push(
          missing("verifier_report", {
            claim_id: claimId,
            required: "linked passing verifier report",
            actual: (error as AuditFailure).code ?? "report_error",
          }),
        );
        continue;
      }
      if (report.outcome !== "pass") {
        missingItems.push(
          missing("verifier_report", {
            claim_id: claimId,
            required: "linked passing verifier report",
            actual: report.outcome,
          }),
        );
        continue;
      }
      if ((report.scope ?? "paper") !== "paper" && report.scope !== `claim:${claimId}`) {
        missingItems.push(
          missing("verifier_report", {
            claim_id: claimId,
            required: `scope paper or claim:${claimId}`,
            actual: report.scope,
          }),
        );
        continue;
      }
      validClaims.add(claimId);
    }
  }
  if (validClaims.size === 0) {
    missingItems.push(
      missing("claims", {
        required: "at least one verified claim whose evidence still matches",
        actual: 0,
      }),
    );
  }

  for (const report of blockingReports(paperDir)) {
    missingItems.push(
      missing("verifier_report", {
        report_id: report.report_id,
        required: "no unoverridden fail or uncertain report",
        actual: report.outcome,
      }),
    );
  }

  return {
    status: missingItems.length === 0 ? "ok" : "incomplete",
    paper_id: manifest.id,
    source_counts: counts,
    valid_ingested_sources: [...validIngested].sort(),
    missing: missingItems,
  };
}

export async function handlePaperAudit(args: {
  paper_id?: string;
}): Promise<Record<string, unknown>> {
  const cfg = runtimeConfig();
  const paperId = args.paper_id ?? activePaperId(cfg.corpusRoot);
  if (!paperId) return { status: "no_active_paper" };
  if (!ID_RE.test(paperId)) {
    return {
      status: "error",
      error_code: "invalid_paper_id",
      message: "Paper IDs use lowercase letters, numbers, and hyphens.",
    };
  }
  try {
    return auditPaper(paperId, cfg.corpusRoot);
  } catch (error) {
    const failure = error as AuditFailure;
    return {
      status: "error",
      error_code: failure.code ?? "audit_error",
      message: failure.message,
    };
  }
}
