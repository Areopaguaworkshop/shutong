import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import JSZip from "jszip";
import { paperDir, readPaper } from "./paper-store.ts";

const ID_RE = /^[a-z0-9][a-z0-9-]{0,62}$/;

function xmlEscape(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#x27;");
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
  readPaper(paperId);
  if (args.draft_requested !== true) {
    return { status: "needs_draft_request", paper_id: paperId };
  }

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
  };
}
