import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { loadVerifierReport, parseNote, verifyClaimEvidence } from "./audit.ts";
import { nextId } from "./ids.ts";
import { paperDir, readPaper, sourcePaper } from "./paper-store.ts";

const ID_RE = /^[a-z0-9][a-z0-9-]{0,62}$/;

class ClaimError extends Error {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

function noteDigest(file: string): string {
  return createHash("sha256").update(readFileSync(file)).digest("hex");
}

export async function handleClaim(args: {
  action?: string;
  paper_id?: string;
  claim_id?: string;
  text?: string;
  note_ids?: string[];
  evidence?: string;
  verifier_report_id?: string;
  report_id?: string;
}): Promise<Record<string, unknown>> {
  try {
    if (!args.paper_id) {
      return { status: "error", error_code: "invalid_input", message: "paper_id is required." };
    }
    const { paper } = sourcePaper(args.paper_id);
    const dir = paperDir(args.paper_id);
    const claimsDir = path.join(dir, "claims");
    const notesDir = path.join(dir, "notes");

    if (args.action === "add") {
      const claimId = args.claim_id ?? nextId(claimsDir, "claim-", ".json");
      if (!ID_RE.test(claimId)) {
        throw new ClaimError("invalid_claim_id", "Claim IDs use lowercase letters, numbers, and hyphens.");
      }
      const file = path.join(claimsDir, `${claimId}.json`);
      if (existsSync(file)) throw new ClaimError("claim_exists", `Claim already exists: ${claimId}`);
      const noteIds = args.note_ids;
      if (!Array.isArray(noteIds) || noteIds.length === 0) {
        throw new ClaimError("missing_claim_evidence", "Claims require one or more verified note IDs.");
      }
      const digests: Record<string, string> = {};
      for (const noteId of noteIds) {
        if (!ID_RE.test(noteId)) throw new ClaimError("invalid_note_id", "Invalid claim note ID.");
        const notePath = path.join(notesDir, `${noteId}.md`);
        const metadata = parseNote(notePath, noteId);
        if (metadata.verified !== true) {
          throw new ClaimError("note_not_verified", `Claim evidence is not a verified note: ${noteId}`);
        }
        const reportId = metadata.verifier_report_id;
        if (!reportId) {
          throw new ClaimError("missing_verification_report", `Claim note has no linked verifier report: ${noteId}`);
        }
        const report = loadVerifierReport(dir, reportId);
        if (report.outcome !== "pass") {
          throw new ClaimError("verifier_report_not_passing", `Claim note has no passing verifier report: ${noteId}`);
        }
        if ((report.scope ?? "paper") !== "paper" && report.scope !== `note:${noteId}`) {
          throw new ClaimError("report_scope_mismatch", `Verifier report ${reportId} does not cover note ${noteId}.`);
        }
        digests[noteId] = noteDigest(notePath);
      }
      const claim = {
        id: claimId,
        text: String(args.text ?? ""),
        note_ids: noteIds,
        note_digests: digests,
        verified: false,
      };
      mkdirSync(claimsDir, { recursive: true });
      writeFileSync(file, `${JSON.stringify(claim, null, 2)}\n`, "utf8");
      return { status: "ok", paper_id: paper.id, claim_id: claimId };
    }

    if (args.action === "verify") {
      const claimId = String(args.claim_id ?? "");
      if (!ID_RE.test(claimId)) {
        throw new ClaimError("invalid_claim_id", "Claim IDs use lowercase letters, numbers, and hyphens.");
      }
      const file = path.join(claimsDir, `${claimId}.json`);
      if (!existsSync(file)) throw new ClaimError("claim_not_found", `Claim not found: ${claimId}`);
      const claim = JSON.parse(readFileSync(file, "utf8"));
      const evidence = String(args.evidence ?? "").trim();
      let reportId = args.verifier_report_id ?? args.report_id;
      if (!reportId && ID_RE.test(evidence)) {
        const candidate = path.join(dir, "audits", `${evidence}.json`);
        if (existsSync(candidate)) reportId = evidence;
      }
      if (!reportId) {
        throw new ClaimError(
          "missing_verification_report",
          "Record a passing verifier report and pass its ID as evidence before verifying.",
        );
      }
      const report = loadVerifierReport(dir, reportId);
      if (report.outcome !== "pass") {
        throw new ClaimError("verifier_report_not_passing", `Verification requires a passing verifier report: ${reportId}`);
      }
      if ((report.scope ?? "paper") !== "paper" && report.scope !== `claim:${claimId}`) {
        throw new ClaimError(
          "report_scope_mismatch",
          `Verifier report ${reportId} is scoped to ${report.scope}, not claim:${claimId}.`,
        );
      }
      if (!evidence) {
        throw new ClaimError(
          "missing_verification_evidence",
          "Verified claims require a passing verifier report; pass its ID as evidence.",
        );
      }
      verifyClaimEvidence(claim, notesDir, paper.id, dir);
      claim.verified = true;
      claim.verification = evidence;
      claim.verifier_report_id = reportId;
      writeFileSync(file, `${JSON.stringify(claim, null, 2)}\n`, "utf8");
      return { status: "ok", paper_id: paper.id, claim_id: claimId };
    }

    return {
      status: "error",
      error_code: "invalid_action",
      message: `Unknown claim action: ${args.action ?? ""}`,
    };
  } catch (error) {
    const failure = error as ClaimError;
    return {
      status: "error",
      error_code: failure.code ?? "claim_error",
      message: failure.message,
    };
  }
}
