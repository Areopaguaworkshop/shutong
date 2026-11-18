import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { runtimeConfig } from "./context.ts";
import { projectRoot, readJsonFile } from "./paths.ts";

interface IngestArgs {
  source?: string;
  is_primary?: boolean;
  text_direction?: string;
  lang?: string;
  doc_type?: string | null;
}

function statusPath(): string {
  return path.join(projectRoot(runtimeConfig().corpusRoot), ".shutong", "ingestion-status.json");
}

function registryPath(): string {
  return path.join(projectRoot(runtimeConfig().corpusRoot), ".shutong", "source-registry.json");
}

export function writeIngestionStatus(payload: Record<string, unknown>): void {
  const file = statusPath();
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(
    file,
    `${JSON.stringify({ ...payload, updated_at: new Date().toISOString() }, null, 2)}\n`,
    "utf8",
  );
}

function archiveRaw(source: string): string | null {
  try {
    if (!existsSync(source) || !statSync(source).isFile()) return null;
    const libraryRoot = process.env.SHUTONG_LIBRARY_ROOT
      ? path.resolve(process.env.SHUTONG_LIBRARY_ROOT)
      : path.join(projectRoot(runtimeConfig().corpusRoot), "library");
    const hash = createHash("sha256").update(readFileSync(source)).digest("hex").slice(0, 16);
    const destination = path.join(libraryRoot, "raw", `${hash}-${path.basename(source)}`);
    mkdirSync(path.dirname(destination), { recursive: true });
    if (!existsSync(destination)) copyFileSync(source, destination);
    return destination;
  } catch {
    return null;
  }
}

function recordSource(
  cslId: string,
  rawPath: string | null,
  documentPath: string | null,
  merkleRoot: string | null,
  isPrimary: boolean,
): void {
  const file = registryPath();
  const records = readJsonFile(file) ?? {};
  records[cslId] = {
    raw_path: rawPath,
    document_path: documentPath,
    merkle_root: merkleRoot,
    role: isPrimary ? "primary" : "unknown",
  };
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, `${JSON.stringify(records, null, 2)}\n`, "utf8");
}

function existingIngestion(source: string): Record<string, unknown> | null {
  const cfg = runtimeConfig();
  let sourcePath: string;
  try {
    sourcePath = path.resolve(source);
  } catch {
    return null;
  }
  if (!existsSync(cfg.corpusRoot)) return null;
  for (const entry of readdirSync(cfg.corpusRoot, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const output = readJsonFile(path.join(cfg.corpusRoot, entry.name, "ingestion_output.json"));
    if (!output) continue;
    const document = output?.sub_pipeline_outputs?.document_json ?? {};
    const recorded = document?.metadata?.source_path;
    if (typeof recorded !== "string" || path.resolve(recorded) !== sourcePath) continue;
    const csl = output?.standardized_csl_json ?? {};
    return {
      status: "ok",
      document_path: path.join(cfg.corpusRoot, entry.name),
      merkle_root: csl.merkle_root ?? null,
      node_count: Array.isArray(document.nodes) ? document.nodes.length : 0,
      doc_type: csl.type ?? csl.source_type ?? null,
      csl_id: csl.id ?? null,
    };
  }
  return null;
}

function nodeCount(document: Record<string, any>): number {
  if (Array.isArray(document.nodes)) return document.nodes.length;
  let count = 0;
  for (const page of Array.isArray(document.pages) ? document.pages : []) {
    count += Array.isArray(page.paragraphs) ? page.paragraphs.length : 0;
    for (const column of Array.isArray(page.columns) ? page.columns : []) {
      count += Array.isArray(column.paragraphs) ? column.paragraphs.length : 0;
    }
  }
  return count;
}

function runCiteindex(args: IngestArgs): Promise<{ stdout: string; stderr: string; code: number | null; error?: Error }> {
  const cfg = runtimeConfig();
  const command = process.env.SHUTONG_CITEINDEX_BIN ?? "citeindex";
  const cliArgs = [String(args.source), "--corpus-root", cfg.corpusRoot, "--quiet"];
  if (args.text_direction) cliArgs.push("--text-direction", args.text_direction);
  if (args.lang) cliArgs.push("--lang", args.lang);
  if (args.doc_type) cliArgs.push("--type", args.doc_type);
  if (process.env.SHUTONG_LLM_MODEL) cliArgs.push("--llm", process.env.SHUTONG_LLM_MODEL);
  return new Promise((resolve) => {
    const child = spawn(command, cliArgs, { env: process.env });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("error", (error) => resolve({ stdout, stderr, code: null, error }));
    child.on("close", (code) => resolve({ stdout, stderr, code }));
  });
}

export async function handleIngest(args: IngestArgs): Promise<Record<string, unknown>> {
  const source = String(args.source ?? "").trim();
  if (!source) {
    return { status: "error", error_code: "invalid_input", message: "source is required" };
  }
  const existing = existingIngestion(source);
  if (existing) {
    const raw = archiveRaw(source);
    if (existing.csl_id) {
      recordSource(
        String(existing.csl_id),
        raw,
        existing.document_path as string,
        existing.merkle_root as string | null,
        args.is_primary === true,
      );
    }
    existing.raw_path = raw;
    writeIngestionStatus(existing);
    return existing;
  }

  writeIngestionStatus({ status: "running", source });
  const result = await runCiteindex(args);
  if (result.error || result.code !== 0) {
    const message = result.error?.message || result.stderr.trim() || `citeindex exited with ${result.code}`;
    const payload = { status: "error", error_code: "ingestion_failed", message };
    writeIngestionStatus(payload);
    return payload;
  }

  let output: Record<string, any>;
  try {
    output = JSON.parse(result.stdout.trim().split("\n").filter(Boolean).pop() ?? "{}");
  } catch {
    const payload = { status: "error", error_code: "invalid_ingestion_output", message: result.stdout.slice(0, 500) };
    writeIngestionStatus(payload);
    return payload;
  }
  if (output.status !== "ok") {
    writeIngestionStatus(output);
    return output;
  }

  const csl = output.standardized_csl_json ?? {};
  const document = output.sub_pipeline_outputs?.document_json ?? {};
  const count = nodeCount(document);
  const payload = {
    status: "ok",
    document_path: output.document_path ?? null,
    merkle_root: csl.merkle_root ?? null,
    node_count: count,
    doc_type: csl.type ?? csl.source_type ?? null,
    csl_id: csl.id ?? null,
    raw_path: archiveRaw(source),
  };
  if (payload.csl_id) {
    recordSource(
      String(payload.csl_id),
      payload.raw_path,
      payload.document_path,
      payload.merkle_root,
      args.is_primary === true,
    );
  }
  writeIngestionStatus(payload);
  return payload;
}
