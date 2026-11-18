import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { getSearchIndex, runtimeConfig } from "./context.ts";

interface SourceRow {
  id: string;
  folder: string;
  csl_json: string;
}

function authorName(author: Record<string, any>): string {
  const family = author?.family ?? author?.literal ?? author?.name ?? author?.suffix ?? "";
  const given = author?.given ?? "";
  return family ? `${family}${given ? `, ${given}` : ""}` : "";
}

function firstAuthorFamily(csl: Record<string, any>): string {
  const first = Array.isArray(csl.author) ? csl.author[0] : undefined;
  return String(first?.family ?? first?.literal ?? first?.name ?? first?.suffix ?? "");
}

function yearOf(csl: Record<string, any>): string {
  const parts = csl?.issued?.["date-parts"];
  const year = Array.isArray(parts) && Array.isArray(parts[0]) ? parts[0][0] : null;
  return year == null ? "n.d." : String(year);
}

function renderChicago(csl: Record<string, any>): { bibliography: string; inText: string } {
  const authors = Array.isArray(csl.author) ? csl.author.map(authorName).filter(Boolean) : [];
  const authorText =
    authors.length === 0
      ? ""
      : authors.length === 1
        ? authors[0]
        : `${authors.slice(0, -1).join(", ")}, and ${authors[authors.length - 1]}`;
  const year = yearOf(csl);
  const title = String(csl.title ?? "").trim();
  const container = String(csl["container-title"] ?? "").trim();
  const publisher = String(csl.publisher ?? "").trim();
  const volume = csl.volume == null ? "" : String(csl.volume);
  const issue = csl.issue == null ? "" : String(csl.issue);
  const page = csl.page == null ? "" : String(csl.page);
  const doi = String(csl.DOI ?? "").trim();
  const url = String(csl.URL ?? "").trim();

  const head = [authorText, year].filter(Boolean).join(". ");
  let result = head ? `${head}.` : "";
  if (title) result += ` “${title}.”`;
  if (container) result += ` ${container}.`;
  if (volume) result += ` ${volume}${issue ? `, no. ${issue}` : ""}.`;
  if (page) result += ` ${page}.`;
  if (publisher) result += ` ${publisher}.`;
  if (doi) result += ` https://doi.org/${doi}.`;
  else if (url) result += ` ${url}.`;
  const bibliography = result.trim();

  const family = firstAuthorFamily(csl) || title || "Anon.";
  const inText = page ? `(${family} ${year}, ${page})` : `(${family} ${year})`;
  return { bibliography, inText };
}

function citationKey(csl: Record<string, any>): string {
  const author = firstAuthorFamily(csl) || "Unknown";
  return `${author} ${yearOf(csl)}`.trim();
}

function matchSource(source: SourceRow, key: string): boolean {
  let csl: Record<string, any> = {};
  try {
    csl = JSON.parse(source.csl_json);
  } catch {
    return false;
  }
  const candidates = [source.id, csl.id, citationKey(csl)]
    .filter((value): value is string => typeof value === "string")
    .map((value) => value.toLowerCase());
  return candidates.includes(key);
}

export async function handleCitation(args: {
  action?: string;
  citation_key?: string;
  csl_id?: string;
}): Promise<Record<string, unknown>> {
  const index = await getSearchIndex();
  const cfg = runtimeConfig();
  const sources = index.db
    .prepare("SELECT id, folder, csl_json FROM sources")
    .all() as unknown as SourceRow[];

  if (args.action === "resolve") {
    const key = String(args.citation_key ?? "").trim().toLowerCase();
    if (!key) {
      return {
        status: "error",
        error_code: "invalid_input",
        message: "citation_key is required for action=resolve",
      };
    }
    const matches: Array<Record<string, unknown>> = [];
    const seen = new Set<string>();
    for (const source of sources) {
      if (!matchSource(source, key) || seen.has(source.id)) continue;
      seen.add(source.id);
      let csl: Record<string, any> = {};
      try {
        csl = JSON.parse(source.csl_json);
      } catch {
        // still return the id and path
      }
      matches.push({
        source_id: source.id,
        title: csl.title ?? "",
        document_path: path.join(cfg.corpusRoot, source.folder),
        citation_key: citationKey(csl),
      });
    }
    if (matches.length === 1) return { status: "ok", ...matches[0] };
    if (matches.length > 1) {
      return {
        status: "ambiguous",
        error_code: "ambiguous_citation",
        message: `${matches.length} documents match ${args.citation_key}; resolve by source id instead.`,
        candidates: matches,
      };
    }
    return {
      status: "error",
      error_code: "not_found",
      message: `No citation matches ${args.citation_key}`,
    };
  }

  if (args.action === "tree") {
    const cslId = String(args.csl_id ?? "");
    const source = sources.find((candidate) => candidate.id === cslId || candidate.folder === cslId);
    if (!source) {
      return {
        status: "error",
        error_code: "not_found",
        message: `Unknown document: ${cslId}`,
      };
    }
    const file = path.join(cfg.corpusRoot, source.folder, "merkle.json");
    if (!existsSync(file)) {
      return {
        status: "error",
        error_code: "not_found",
        message: `No merkle tree for ${source.id}`,
      };
    }
    return {
      status: "ok",
      csl_id: source.id,
      tree: JSON.parse(readFileSync(file, "utf8")),
    };
  }

  if (args.action === "render") {
    const cslId = String(args.csl_id ?? "");
    const source = sources.find((candidate) => candidate.id === cslId || candidate.folder === cslId);
    if (!source) {
      return { status: "error", error_code: "not_found", message: `Unknown document: ${cslId}` };
    }
    const style = String((args as any).style ?? "chicago-author-date");
    if (style !== "chicago-author-date") {
      return {
        status: "error",
        error_code: "unsupported_style",
        message: `Only chicago-author-date is implemented; requested ${style}.`,
        next_action: "Use style=chicago-author-date.",
      };
    }
    let csl: Record<string, any>;
    try {
      csl = JSON.parse(source.csl_json);
    } catch {
      return { status: "error", error_code: "invalid_csl", message: `CSL record is unreadable: ${source.id}` };
    }
    const rendered = renderChicago(csl);
    return {
      status: "ok",
      csl_id: source.id,
      style,
      bibliography: rendered.bibliography,
      in_text: rendered.inText,
      engine: "ts-native-chicago",
    };
  }

  return {
    status: "error",
    error_code: "invalid_action",
    message: `Unknown citation action: ${args.action ?? ""}`,
    next_action: "Use action=resolve, render, or tree.",
  };
}
