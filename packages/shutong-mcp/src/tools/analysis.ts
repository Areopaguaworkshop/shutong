import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { buildMerkleTree, hashPayload, pythonJsonDumpsSpaced, sha256Hex } from "../contract/hash.ts";
import { canonicalizeText } from "../search/tokenize.ts";
import { getSearchIndex, runtimeConfig } from "./context.ts";
import { paperDir, readPaper, sourcePaper } from "./paper-store.ts";

const MODES = ["concordance", "collocations", "contextual_sentiment", "quotation", "text_reuse"] as const;
const LABELS = new Set(["favorable", "unfavorable", "neutral", "mixed", "uncertain"]);
const VERSION = "text-analysis-v1";

interface Token {
  token: string;
  start: number;
  end: number;
}

interface AnalysisNode {
  node_id: string;
  source_id: string;
  section_path: string;
  text: string;
  sha256: string;
  page: number;
  is_footnote?: boolean;
}

interface AnalysisSource {
  source_id: string;
  merkle_root: string;
  snapshot_sha256: string;
  csl: Record<string, any>;
}

class AnalysisError extends Error {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

function digest(value: unknown): string {
  return sha256Hex(pythonJsonDumpsSpaced(value));
}

function now(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "+00:00");
}

function isHan(cp: number): boolean {
  return (cp >= 0x3400 && cp <= 0x4dbf) || (cp >= 0x4e00 && cp <= 0x9fff) || (cp >= 0x20000 && cp <= 0x323af);
}

function isWordCategory(char: string): boolean {
  return /[\p{L}\p{M}\p{N}]/u.test(char);
}

export function analysisTokens(text: string): Token[] {
  const tokens: Token[] = [];
  let start: number | null = null;
  for (let index = 0; index < text.length; ) {
    const cp = text.codePointAt(index)!;
    const char = String.fromCodePoint(cp);
    const width = char.length;
    const han = isHan(cp);
    const apostrophe =
      (char === "'" || char === "\u2019") &&
      start !== null &&
      index + width < text.length &&
      /[\p{L}]/u.test(String.fromCodePoint(text.codePointAt(index + width)!));
    const word = isWordCategory(char) || apostrophe;
    if (start !== null && (han || !word)) {
      tokens.push({ token: text.slice(start, index).normalize("NFC").toLowerCase(), start, end: index });
      start = null;
    }
    if (han) {
      tokens.push({ token: char, start: index, end: index + width });
    } else if (word && start === null) {
      start = index;
    }
    index += width;
  }
  if (start !== null) {
    tokens.push({ token: text.slice(start).normalize("NFC").toLowerCase(), start, end: text.length });
  }
  return tokens;
}

function span(node: AnalysisNode, start: number, end: number): Record<string, unknown> {
  return {
    source_id: node.source_id,
    node_id: node.node_id,
    node_sha256: node.sha256,
    page: node.page,
    section_path: node.section_path,
    start,
    end,
    text: node.text.slice(start, end),
  };
}

function requiredText(args: Record<string, any>, key: string): string {
  const value = args[key];
  if (typeof value !== "string" || !value.trim() || value.length > 10000) {
    throw new AnalysisError("invalid_input", `${key} must be non-empty text of at most 10000 characters.`);
  }
  return value;
}

function integer(args: Record<string, any>, key: string, fallback: number, low: number, high: number): number {
  const value = args[key] ?? fallback;
  if (!Number.isInteger(value) || value < low || value > high) {
    throw new AnalysisError("invalid_input", `${key} must be an integer from ${low} to ${high}.`);
  }
  return value;
}

function contextSearch(
  nodes: AnalysisNode[],
  query: string,
  radius: number,
  limit: number,
  exact: boolean,
): Record<string, unknown> {
  const wanted = analysisTokens(query).map((token) => token.token);
  if (!exact && wanted.length === 0) {
    throw new AnalysisError("invalid_input", "query must contain a word or Han character.");
  }
  const contexts: Array<Record<string, unknown>> = [];
  let count = 0;
  for (const node of nodes) {
    const text = node.text;
    const spans: Array<[number, number]> = [];
    if (exact) {
      let from = 0;
      while (true) {
        const found = text.indexOf(query, from);
        if (found < 0) break;
        spans.push([found, found + query.length]);
        from = found + 1;
      }
    } else {
      const tokens = analysisTokens(text);
      for (let index = 0; index + wanted.length <= tokens.length; index += 1) {
        if (tokens.slice(index, index + wanted.length).every((token, offset) => token.token === wanted[offset])) {
          spans.push([tokens[index].start, tokens[index + wanted.length - 1].end]);
        }
      }
    }
    for (const [start, end] of spans) {
      count += 1;
      if (contexts.length < limit) {
        contexts.push({
          ...span(node, start, end),
          left: text.slice(Math.max(0, start - radius), start),
          right: text.slice(end, end + radius),
        });
      }
    }
  }
  return { contexts, total_occurrences: count, returned: contexts.length, truncated: count > contexts.length };
}

function collocations(nodes: AnalysisNode[], query: string, window: number, limit: number): Record<string, unknown> {
  const wanted = analysisTokens(query).map((token) => token.token);
  if (wanted.length === 0) {
    throw new AnalysisError("invalid_input", "query must contain a word or Han character.");
  }
  const counts = new Map<string, number>();
  const documents = new Map<string, Set<string>>();
  const examples = new Map<string, Record<string, unknown>>();
  let occurrences = 0;
  let totalTokens = 0;
  for (const node of nodes) {
    const tokens = analysisTokens(node.text);
    totalTokens += tokens.length;
    for (let index = 0; index + wanted.length <= tokens.length; index += 1) {
      if (!tokens.slice(index, index + wanted.length).every((token, offset) => token.token === wanted[offset])) continue;
      occurrences += 1;
      const positions: number[] = [];
      for (let position = Math.max(0, index - window); position < index; position += 1) positions.push(position);
      for (
        let position = index + wanted.length;
        position < Math.min(tokens.length, index + wanted.length + window);
        position += 1
      ) {
        positions.push(position);
      }
      for (const position of positions) {
        const token = tokens[position];
        counts.set(token.token, (counts.get(token.token) ?? 0) + 1);
        if (!documents.has(token.token)) documents.set(token.token, new Set());
        documents.get(token.token)!.add(node.source_id);
        if (!examples.has(token.token)) {
          examples.set(token.token, {
            collocate: span(node, token.start, token.end),
            target: span(node, tokens[index].start, tokens[index + wanted.length - 1].end),
          });
        }
      }
    }
  }
  const ordered = [...counts.keys()].sort((a, b) => (counts.get(b)! - counts.get(a)!) || (a < b ? -1 : a > b ? 1 : 0));
  return {
    target_occurrences: occurrences,
    corpus_tokens: totalTokens,
    total_collocates: ordered.length,
    truncated: ordered.length > limit,
    collocates: ordered.slice(0, limit).map((token) => ({
      token,
      count: counts.get(token),
      document_frequency: documents.get(token)!.size,
      example: examples.get(token),
    })),
  };
}

function reuse(nodes: AnalysisNode[], width: number, limit: number): Record<string, unknown> {
  const windows = new Map<string, Array<[AnalysisNode, number, number]>>();
  let total = 0;
  for (const node of nodes) {
    const tokens = analysisTokens(node.text);
    for (let index = 0; index + width <= tokens.length; index += 1) {
      total += 1;
      if (total > 200000) {
        throw new AnalysisError("analysis_too_large", "Exact reuse is limited to 200000 token windows; narrow the source set.");
      }
      const key = JSON.stringify(tokens.slice(index, index + width).map((token) => token.token));
      const occurrences = windows.get(key) ?? [];
      occurrences.push([node, tokens[index].start, tokens[index + width - 1].end]);
      windows.set(key, occurrences);
    }
  }
  const matches: Array<Record<string, unknown>> = [];
  let groups = 0;
  for (const key of [...windows.keys()].sort()) {
    const occurrences = windows.get(key)!;
    if (new Set(occurrences.map(([node]) => node.source_id)).size < 2) continue;
    groups += 1;
    if (matches.length < limit) {
      matches.push({
        tokens: JSON.parse(key),
        occurrences: occurrences.slice(0, limit).map(([node, start, end]) => span(node, start, end)),
        total_occurrences: occurrences.length,
        occurrences_truncated: occurrences.length > limit,
      });
    }
  }
  return { matches, total_match_groups: groups, truncated: groups > limit, windows_checked: total };
}

function analysisNodeList(document: any, sourceId: string): AnalysisNode[] {
  if (!document || typeof document !== "object") return [];
  if (Array.isArray(document.nodes) && document.nodes.length > 0) {
    return document.nodes
      .filter((node: any) => String(node?.text ?? "").trim())
      .map((node: any, index: number) => {
        const text = String(node.text ?? "");
        return {
          ...node,
          source_id: sourceId,
          section_path: node.section_path ?? `p${node.page ?? 0}`,
          sha256: String(node.sha256 ?? sha256Hex(canonicalizeText(text))),
          page: Number(node.page ?? node.physical_page_index ?? 0) || 0,
          node_id: String(node.node_id ?? `${sourceId}:p${node.page ?? 0}:node${index}`),
        } as AnalysisNode;
      });
  }
  const nodes: AnalysisNode[] = [];
  for (const page of Array.isArray(document.pages) ? document.pages : []) {
    const pageNumber = Number(page?.page_number ?? 0) || 0;
    const columns = Array.isArray(page?.columns) ? page.columns : [];
    const paragraphs = columns.length
      ? columns.flatMap((column: any) => (Array.isArray(column?.paragraphs) ? column.paragraphs : []))
      : Array.isArray(page?.paragraphs)
        ? page.paragraphs
        : [];
    paragraphs.forEach((para: any, index: number) => {
      const text = canonicalizeText(para?.text);
      if (!text) return;
      const hash = sha256Hex(text);
      nodes.push({
        node_id: `${sourceId}:p${pageNumber}:${para?.paragraph_id ?? `p${pageNumber}_unk`}:${hash.slice(0, 8)}`,
        source_id: sourceId,
        section_path: `p${pageNumber}`,
        text,
        sha256: hash,
        page: pageNumber,
      });
    });
    for (const footnote of Array.isArray(page?.footnotes) ? page.footnotes : []) {
      if (!footnote || typeof footnote !== "object" || !footnote.text) continue;
      const text = canonicalizeText(footnote.text);
      if (!text) continue;
      const hash = sha256Hex(text);
      nodes.push({
        node_id: `${sourceId}:p${pageNumber}:fn:${hash.slice(0, 8)}`,
        source_id: sourceId,
        section_path: `p${pageNumber}`,
        text,
        sha256: hash,
        page: pageNumber,
        is_footnote: true,
      });
    }
  }
  return nodes;
}

async function scope(
  paperId: string,
  sourceIds: string[],
): Promise<{ nodes: AnalysisNode[]; sources: AnalysisSource[] }> {
  const { sourcePaper: manifest } = sourcePaper(paperId);
  if (manifest.bibliography?.status !== "approved") {
    throw new AnalysisError("bibliography_not_approved", "Approve the source bibliography before analysis.");
  }
  if (
    !Array.isArray(sourceIds) ||
    sourceIds.length < 1 ||
    sourceIds.length > 50 ||
    new Set(sourceIds).size !== sourceIds.length
  ) {
    throw new AnalysisError("invalid_input", "source_ids must contain 1–50 unique source IDs.");
  }
  const approved = new Set((manifest.bibliography?.entries ?? []).map((entry: any) => entry.id));
  const ingested = new Set((manifest.sources ?? []).filter((source: any) => source.ingested).map((source: any) => source.source_id));
  if (!sourceIds.every((id) => approved.has(id) && ingested.has(id))) {
    throw new AnalysisError("source_not_ingested", "Analysis requires approved, ingested sources belonging to this paper.");
  }

  const index = await getSearchIndex();
  const cfg = runtimeConfig();
  const nodes: AnalysisNode[] = [];
  const sources: AnalysisSource[] = [];
  for (const sourceId of [...sourceIds].sort()) {
    const rows = index.db
      .prepare("SELECT id, folder, csl_json FROM sources WHERE id=?")
      .all(sourceId) as unknown as Array<{ id: string; folder: string; csl_json: string }>;
    if (rows.length !== 1) throw new AnalysisError("unverified_source", `Missing or ambiguous corpus evidence: ${sourceId}`);
    const row = rows[0];
    const document = JSON.parse(readFileSync(path.join(cfg.corpusRoot, row.folder, "document.json"), "utf8"));
    const merkle = JSON.parse(readFileSync(path.join(cfg.corpusRoot, row.folder, "merkle.json"), "utf8"));
    const selected = analysisNodeList(document, sourceId);
    if (selected.length === 0 || !merkle?.root || !Array.isArray(merkle?.levels)) {
      throw new AnalysisError("unverified_source", `Missing or ambiguous corpus evidence: ${sourceId}`);
    }
    const rebuilt = buildMerkleTree(merkle.levels[0]).root;
    if (rebuilt !== merkle.root) throw new AnalysisError("unverified_source", `Source integrity failed: ${sourceId}`);
    if (selected.some((node) => !merkle.levels[0].includes(node.sha256))) {
      throw new AnalysisError("unverified_source", `Source integrity failed: ${sourceId}`);
    }
    if (selected.some((node) => hashPayload(node.text) !== node.sha256)) {
      throw new AnalysisError("unverified_source", `Source integrity failed: ${sourceId}`);
    }
    nodes.push(...selected);
    sources.push({
      source_id: sourceId,
      merkle_root: merkle.root,
      snapshot_sha256: digest(selected),
      csl: JSON.parse(row.csl_json),
    });
  }
  if (nodes.length > 5000 || nodes.reduce((sum, node) => sum + node.text.length, 0) > 2_000_000) {
    throw new AnalysisError("analysis_too_large", "Narrow source selection to 5000 nodes and 2 million characters per run.");
  }
  return { nodes, sources };
}

function analysisPath(paperId: string, analysisId: string): string {
  if (!/^analysis-[a-f0-9]{32}$/.test(analysisId)) {
    throw new AnalysisError("invalid_input", "Invalid analysis_id.");
  }
  readPaper(paperId);
  return path.join(paperDir(paperId), "analyses", `${analysisId}.json`);
}

function saveRecord(record: Record<string, any>): void {
  const file = analysisPath(record.paper_id, record.analysis_id);
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, `${JSON.stringify(record, null, 2)}\n`, "utf8");
}

function response(record: Record<string, any>): Record<string, unknown> {
  return { status: "ok", analysis: record, record_sha256: digest(record) };
}

function loadRecord(paperId: string, analysisId: string): Record<string, any> {
  const file = analysisPath(paperId, analysisId);
  if (!existsSync(file)) throw new AnalysisError("analysis_not_found", "Analysis not found in this paper.");
  return JSON.parse(readFileSync(file, "utf8"));
}

async function runAnalysis(args: Record<string, any>): Promise<Record<string, unknown>> {
  const mode = args.mode;
  if (!MODES.includes(mode) || !["en", "zh"].includes(args.language)) {
    throw new AnalysisError("invalid_input", "Choose a supported analysis mode and language (en or zh).");
  }
  if (args.library_wide) {
    throw new AnalysisError("invalid_input", "Analysis requires an explicit paper source set.");
  }
  requiredText(args, "question");
  const limit = integer(args, "limit", 100, 1, 200);
  const radius = integer(args, "context", 160, 20, 1000);
  const window = integer(args, "window", 5, 1, 20);
  const width = integer(args, "minimum_tokens", 8, 4, 30);
  const query = mode === "text_reuse" ? "" : requiredText(args, "query");
  const rubric = mode === "contextual_sentiment" ? requiredText(args, "rubric") : null;
  if (mode === "text_reuse" && (!Array.isArray(args.source_ids) || args.source_ids.length < 2)) {
    throw new AnalysisError("invalid_input", "Source reuse requires at least two source IDs.");
  }
  const { nodes, sources } = await scope(args.paper_id, args.source_ids);
  const parameters = { query, language: args.language, window, minimum_tokens: width, context: radius, limit, rubric };
  const result =
    mode === "collocations"
      ? collocations(nodes, query, window, limit)
      : mode === "text_reuse"
        ? reuse(nodes, width, limit)
        : contextSearch(nodes, query, radius, limit, mode === "quotation");
  const record = {
    schema_version: 1,
    analysis_id: `analysis-${randomUUID().replaceAll("-", "")}`,
    paper_id: args.paper_id,
    created_at: now(),
    question: args.question,
    mode,
    method: VERSION,
    tokenizer: "unicode-words-han-characters-v1",
    parameters,
    sources,
    node_count: nodes.length,
    results: result,
    annotations: [],
    review: { outcome: "pending" },
    limitations: [
      "Matches and windows do not cross corpus node boundaries; Han units are characters, not segmented words.",
      "Collocations count neighboring tokens per target occurrence, without significance or causal inference.",
      "Reuse means equal NFC/casefolded token sequences; punctuation is ignored. It is not proof of borrowing or plagiarism.",
      "Quotation matching is case-sensitive and exact in the ingested text, not a check against the original page image.",
      "Contextual sentiment is agent interpretation under the supplied rubric; no automatic sentiment scores are computed.",
      "Merkle checks concern local corpus integrity, not historical authenticity or semantic claim support.",
    ],
  };
  saveRecord(record);
  return response(record);
}

async function getAnalysis(args: Record<string, any>): Promise<Record<string, unknown>> {
  const record = loadRecord(args.paper_id, args.analysis_id);
  const { sources } = await scope(args.paper_id, record.sources.map((source: any) => source.source_id));
  if (JSON.stringify(sources) !== JSON.stringify(record.sources)) {
    throw new AnalysisError("stale_analysis", "Source text, locations or bibliography changed; rerun the analysis.");
  }
  return response(record);
}

async function annotateAnalysis(args: Record<string, any>): Promise<Record<string, unknown>> {
  const current = await getAnalysis(args);
  const record = current.analysis as Record<string, any>;
  if (args.record_sha256 !== current.record_sha256) {
    throw new AnalysisError("stale_analysis", "Read the latest analysis before annotating it.");
  }
  if (record.mode !== "contextual_sentiment") {
    throw new AnalysisError("invalid_input", "Annotations are supported for contextual sentiment only.");
  }
  const annotations = args.annotations;
  if (!Array.isArray(annotations) || annotations.length < 1 || annotations.length > record.results.contexts.length) {
    throw new AnalysisError("invalid_input", "Provide annotations for one or more returned contexts.");
  }
  const seen = new Set<number>();
  const clean: Array<Record<string, unknown>> = [];
  for (const item of annotations) {
    if (!item || typeof item !== "object") throw new AnalysisError("invalid_input", "Each annotation must be an object.");
    const index = integer(item, "context_index", -1, 0, record.results.contexts.length - 1);
    if (seen.has(index) || !LABELS.has(item.label) || !["known", "probable", "speculative"].includes(item.confidence)) {
      throw new AnalysisError("invalid_input", "Use unique context indices, a supported label and explicit confidence.");
    }
    seen.add(index);
    clean.push({
      context_index: index,
      label: item.label,
      confidence: item.confidence,
      target: requiredText(item, "target"),
      speaker: requiredText(item, "speaker"),
      rationale: requiredText(item, "rationale"),
    });
  }
  record.annotations = clean;
  record.interpretation = {
    model_id: requiredText(args, "model_id"),
    recorded_at: now(),
    reproducibility: "Model identity is recorded; identical future interpretations are not guaranteed.",
  };
  record.review = { outcome: "pending" };
  saveRecord(record);
  return response(record);
}

async function reviewAnalysis(args: Record<string, any>): Promise<Record<string, unknown>> {
  const current = await getAnalysis(args);
  const record = current.analysis as Record<string, any>;
  if (args.record_sha256 !== current.record_sha256) {
    throw new AnalysisError("stale_analysis", "Review must reference the exact inspected record_sha256.");
  }
  if (!["pass", "fail", "uncertain"].includes(args.outcome)) {
    throw new AnalysisError("invalid_input", "Review outcome must be pass, fail or uncertain.");
  }
  if (args.outcome === "pass" && record.mode === "contextual_sentiment" && record.annotations.length === 0) {
    throw new AnalysisError("missing_interpretation", "Context retrieval alone cannot verify a sentiment interpretation.");
  }
  record.review = {
    outcome: args.outcome,
    evidence: requiredText(args, "evidence"),
    reviewer: requiredText(args, "reviewer"),
    recorded_at: now(),
    inspected_sha256: current.record_sha256,
  };
  saveRecord(record);
  return response(record);
}

export async function handleAnalysis(args: Record<string, any>): Promise<Record<string, unknown>> {
  try {
    if (!args.paper_id) {
      return { status: "error", error_code: "invalid_input", message: "paper_id is required." };
    }
    switch (args.action) {
      case "run":
        return await runAnalysis(args);
      case "get":
        return await getAnalysis(args);
      case "annotate":
        return await annotateAnalysis(args);
      case "review":
        return await reviewAnalysis(args);
      default:
        return { status: "error", error_code: "invalid_input", message: "Unknown analysis action." };
    }
  } catch (error) {
    const failure = error as AnalysisError;
    return {
      status: "error",
      error_code: failure.code ?? "analysis_error",
      message: failure.message,
    };
  }
}
