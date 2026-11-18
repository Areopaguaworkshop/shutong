import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import JSZip from "jszip";
import { verifyClaimEvidence } from "./audit.ts";
import { paperDir, readPaper } from "./paper-store.ts";
import { handlePaperAudit } from "./audit.ts";

const ID_RE = /^[a-z0-9][a-z0-9-]{0,62}$/;

function xmlEscape(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#x27;");
}

function readClaims(paperId: string): Array<Record<string, any>> {
  const dir = path.join(paperDir(paperId), "claims");
  if (!existsSync(dir)) return [];
  const claims: Array<Record<string, any>> = [];
  for (const file of readdirSync(dir).filter((name) => name.endsWith(".json")).sort()) {
    try {
      const claim = JSON.parse(readFileSync(path.join(dir, file), "utf8"));
      if (claim?.verified === true) claims.push(claim);
    } catch {
      // ignore unreadable claims; the audit already reports them
    }
  }
  return claims;
}

async function draftContext(paperId: string, draftRequested: boolean): Promise<Record<string, unknown>> {
  const audit = await handlePaperAudit({ paper_id: paperId });
  if (audit.status !== "ok") {
    return {
      status: "needs_evidence",
      paper_id: audit.paper_id ?? paperId,
      missing: audit.missing ?? [],
    };
  }
  if (!draftRequested) {
    return {
      status: "needs_draft_request",
      paper_id: paperId,
      message: "Ask explicitly for a draft after reviewing the verified notes and claims.",
    };
  }
  const notesDir = path.join(paperDir(paperId), "notes");
  const claims: Array<Record<string, any>> = [];
  for (const claim of readClaims(paperId)) {
    try {
      verifyClaimEvidence(claim, notesDir, paperId, paperDir(paperId));
      claims.push(claim);
    } catch {
      // a stale claim is a missing claim for drafting
    }
  }
  if (claims.length === 0) {
    return {
      status: "needs_evidence",
      paper_id: paperId,
      missing: [{ stage: "claims", required: "at least one verified claim", actual: 0 }],
    };
  }
  return {
    status: "ready",
    paper_id: paperId,
    title: readPaper(paperId).title ?? "",
    claims,
  };
}

export async function handleExportDocx(args: {
  paper_id?: string;
  draft?: string;
  filename?: string;
  draft_requested?: boolean;
}): Promise<Record<string, unknown>> {
  const paperId = String(args.paper_id ?? "");
  if (!paperId || !ID_RE.test(paperId)) {
    return { status: "error", error_code: "invalid_input", message: "paper_id is required." };
  }
  const context = await draftContext(paperId, args.draft_requested === true);
  if (context.status !== "ready") return context;

  const draft = args.draft;
  if (typeof draft !== "string" || !draft.trim()) {
    return { status: "error", error_code: "empty_draft", message: "DOCX export requires non-empty draft Markdown." };
  }
  const filename = String(args.filename ?? "draft");
  if (!ID_RE.test(filename)) {
    return {
      status: "error",
      error_code: "invalid_draft_filename",
      message: "Draft filenames use lowercase letters, numbers, and hyphens.",
    };
  }

  const paragraphs = draft
    .split(/\r?\n/)
    .filter((line) => line.trim())
    .map((line) => `<w:p><w:r><w:t xml:space="preserve">${xmlEscape(line)}</w:t></w:r></w:p>`)
    .join("");
  const document =
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">' +
    `<w:body>${paragraphs}<w:sectPr/></w:body></w:document>`;

  const zip = new JSZip();
  zip.file(
    "[Content_Types].xml",
    '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
  );
  zip.file(
    "_rels/.rels",
    '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
  );
  zip.file("word/document.xml", document);
  const buffer = await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" });
  const target = path.join(paperDir(paperId), "drafts", `${filename}.docx`);
  mkdirSync(path.dirname(target), { recursive: true });
  writeFileSync(target, buffer);
  return {
    status: "ok",
    paper_id: paperId,
    path: target,
    claim_count: (context.claims as unknown[]).length,
  };
}
