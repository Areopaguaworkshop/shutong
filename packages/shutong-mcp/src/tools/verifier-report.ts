import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { paperDir, readPaper } from "./paper-store.ts";
import { nextId } from "./ids.ts";

const ID_RE = /^[a-z0-9][a-z0-9-]{0,62}$/;

class ReportError extends Error {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

function loadReport(paperId: string, reportId: string): Record<string, any> {
  if (!ID_RE.test(reportId)) {
    throw new ReportError("invalid_report_id", "Report IDs use lowercase letters, numbers, and hyphens.");
  }
  const file = path.join(paperDir(paperId), "audits", `${reportId}.json`);
  if (!existsSync(file)) throw new ReportError("report_not_found", `Verifier report not found: ${reportId}`);
  try {
    const report = JSON.parse(readFileSync(file, "utf8"));
    if (!report || typeof report !== "object" || Array.isArray(report)) {
      throw new Error("not an object");
    }
    return report;
  } catch {
    throw new ReportError("invalid_verifier_report", `Verifier report cannot be read: ${reportId}`);
  }
}

export async function handleVerifierReport(args: {
  action?: string;
  paper_id?: string;
  outcome?: string;
  report_id?: string;
  scope?: string;
  evidence?: string;
  defect?: string;
  residual_risk?: string;
  reason?: string;
}): Promise<Record<string, unknown>> {
  try {
    if (!args.paper_id) {
      return { status: "error", error_code: "invalid_input", message: "paper_id is required." };
    }
    readPaper(args.paper_id);
    const audits = path.join(paperDir(args.paper_id), "audits");
    mkdirSync(audits, { recursive: true });

    if (args.action === "record") {
      if (!["pass", "fail", "uncertain"].includes(String(args.outcome))) {
        throw new ReportError("invalid_verifier_outcome", "Verifier outcome must be pass, fail, or uncertain.");
      }
      const reportId = args.report_id ?? nextId(audits, "verifier-", ".json");
      if (!ID_RE.test(reportId)) {
        throw new ReportError("invalid_report_id", "Report IDs use lowercase letters, numbers, and hyphens.");
      }
      const reportPath = path.join(audits, `${reportId}.json`);
      if (existsSync(reportPath)) {
        throw new ReportError("report_exists", `Verifier report already exists: ${reportId}`);
      }
      const report = {
        id: reportId,
        outcome: args.outcome,
        scope: args.scope ?? "paper",
        evidence: String(args.evidence ?? ""),
        defect: String(args.defect ?? ""),
        residual_risk: String(args.residual_risk ?? ""),
      };
      writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
      return { status: "ok", paper_id: args.paper_id, report_id: reportId, outcome: args.outcome };
    }

    if (args.action === "override") {
      const reportId = String(args.report_id ?? "");
      const report = loadReport(args.paper_id, reportId);
      if (report.outcome === "pass") {
        throw new ReportError("override_not_needed", "Only fail or uncertain verifier reports can be overridden.");
      }
      const reason = String(args.reason ?? "").trim();
      if (!reason) {
        throw new ReportError(
          "missing_override_reason",
          "Scholar overrides require a reason and visible residual risk.",
        );
      }
      const override = {
        report_id: reportId,
        reason,
        residual_risk: args.residual_risk ?? report.residual_risk ?? "",
      };
      writeFileSync(path.join(audits, "overrides.jsonl"), `${JSON.stringify(override)}\n`, {
        encoding: "utf8",
        flag: "a",
      });
      return { status: "ok", paper_id: args.paper_id, report_id: reportId, override };
    }

    return {
      status: "error",
      error_code: "invalid_action",
      message: `Unknown verifier_report action: ${args.action ?? ""}`,
    };
  } catch (error) {
    const failure = error as ReportError;
    return {
      status: "error",
      error_code: failure.code ?? "verifier_report_error",
      message: failure.message,
    };
  }
}
