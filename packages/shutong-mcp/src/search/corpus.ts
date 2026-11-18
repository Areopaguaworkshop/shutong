import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { canonicalizeText, tokenize } from "./tokenize.ts";
import { sha256Hex } from "../contract/hash.ts";

export { sha256Hex };

export interface SourceNode {
  node_id: string;
  source_id: string;
  page: number;
  para: number;
  text: string;
  tokens: string;
  sha256: string;
}

export interface SourceRecord {
  id: string;
  folder: string;
  contentHash: string | null;
  csl: Record<string, unknown>;
  title: string;
  authorText: string;
  year: number | null;
  doi: string | null;
  url: string | null;
  nodes: SourceNode[];
}

function readJson(file: string): any | null {
  if (!existsSync(file)) return null;
  try {
    return JSON.parse(readFileSync(file, "utf8"));
  } catch {
    return null;
  }
}

function firstAuthor(csl: Record<string, any>): string {
  const author = Array.isArray(csl.author) ? csl.author[0] : undefined;
  if (!author) return "";
  return String(author.family ?? author.literal ?? author.name ?? "");
}

function authorText(csl: Record<string, any>): string {
  if (!Array.isArray(csl.author)) return "";
  return csl.author
    .map((author: any) => String(author?.family ?? author?.literal ?? author?.name ?? ""))
    .filter(Boolean)
    .join(", ");
}

function issuedYear(csl: Record<string, any>): number | null {
  const parts = csl?.issued?.["date-parts"];
  const year = Array.isArray(parts) && Array.isArray(parts[0]) ? Number(parts[0][0]) : NaN;
  return Number.isFinite(year) ? year : null;
}

function paragraphNode(
  sourceId: string,
  page: number,
  para: number,
  paraId: string,
  rawText: unknown,
): SourceNode | null {
  const text = canonicalizeText(rawText);
  if (!text) return null;
  const hash = sha256Hex(text);
  return {
    node_id: `${sourceId}:p${page}:${paraId}:${hash.slice(0, 8)}`,
    source_id: sourceId,
    page,
    para,
    text,
    tokens: tokenize(text),
    sha256: hash,
  };
}

/**
 * Mirror of Shutong's CorpusLoader._extract_nodes_from_document.
 *
 * Pre-built `document.nodes` are kept as authored; hierarchical pages use
 * paragraph text (not the `lines` array, which CorpusLoader ignores) and
 * footnotes become their own nodes.
 */
export function extractNodes(document: any, sourceId: string): SourceNode[] {
  if (!document || typeof document !== "object") return [];

  if (Array.isArray(document.nodes) && document.nodes.length > 0) {
    return document.nodes
      .map((node: any, index: number): SourceNode | null => {
        const text = String(node?.text ?? "");
        if (!text.trim()) return null;
        const page = Number(node?.page ?? node?.physical_page_index ?? 0) || 0;
        const hash = String(node?.sha256 ?? sha256Hex(canonicalizeText(text)));
        return {
          node_id: String(node?.node_id ?? `${sourceId}:p${page}:node${index}:${hash.slice(0, 8)}`),
          source_id: sourceId,
          page,
          para: Number(node?.paragraph_index ?? index) || 0,
          text,
          tokens: tokenize(text),
          sha256: hash,
        };
      })
      .filter((node: SourceNode | null): node is SourceNode => node !== null);
  }

  const nodes: SourceNode[] = [];
  for (const page of Array.isArray(document.pages) ? document.pages : []) {
    const pageNumber = Number(page?.page_number ?? 0) || 0;
    const columns = Array.isArray(page?.columns) ? page.columns : [];
    const paragraphs = columns.length
      ? columns.flatMap((column: any) => (Array.isArray(column?.paragraphs) ? column.paragraphs : []))
      : Array.isArray(page?.paragraphs)
        ? page.paragraphs
        : [];

    paragraphs.forEach((para: any, index: number) => {
      const node = paragraphNode(
        sourceId,
        pageNumber,
        index,
        String(para?.paragraph_id ?? `p${pageNumber}_unk`),
        para?.text,
      );
      if (node) nodes.push(node);
    });

    for (const footnote of Array.isArray(page?.footnotes) ? page.footnotes : []) {
      if (!footnote || typeof footnote !== "object" || !footnote.text) continue;
      const text = canonicalizeText(footnote.text);
      if (!text) continue;
      const hash = sha256Hex(text);
      nodes.push({
        node_id: `${sourceId}:p${pageNumber}:fn:${hash.slice(0, 8)}`,
        source_id: sourceId,
        page: pageNumber,
        para: -1,
        text,
        tokens: tokenize(text),
        sha256: hash,
      });
    }
  }
  return nodes;
}

export function loadSource(corpusRoot: string, folder: string): SourceRecord | null {
  const dir = path.join(corpusRoot, folder);
  const csl = readJson(path.join(dir, "csl.json"));
  if (!csl || typeof csl !== "object") return null;

  const document = readJson(path.join(dir, "document.json"));
  const sourceId = String((csl as any).id ?? folder);
  const nodes = extractNodes(document, sourceId);

  return {
    id: sourceId,
    folder,
    contentHash: typeof (csl as any).content_hash === "string" ? (csl as any).content_hash : null,
    csl: csl as Record<string, unknown>,
    title: String((csl as any).title ?? firstAuthor(csl as any) ?? ""),
    authorText: authorText(csl as any),
    year: issuedYear(csl as any),
    doi: typeof (csl as any).DOI === "string" ? (csl as any).DOI : null,
    url: typeof (csl as any).URL === "string" ? (csl as any).URL : null,
    nodes,
  };
}

export function listCorpusFolders(corpusRoot: string): string[] {
  if (!existsSync(corpusRoot)) return [];
  return readdirSync(corpusRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && existsSync(path.join(corpusRoot, entry.name, "csl.json")))
    .map((entry) => entry.name)
    .sort();
}
