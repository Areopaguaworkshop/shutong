import { existsSync, readdirSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { getSearchIndex, runtimeConfig } from "./context.ts";
import { projectRoot, readJsonFile } from "./paths.ts";

export async function handleIngestStatus(): Promise<Record<string, unknown>> {
  const file = path.join(projectRoot(runtimeConfig().corpusRoot), ".shutong", "ingestion-status.json");
  if (!existsSync(file)) return { status: "idle" };
  try {
    return JSON.parse(readFileSync(file, "utf8"));
  } catch {
    return { status: "idle" };
  }
}

export async function handleDeleteDocument(args: {
  csl_id?: string;
}): Promise<Record<string, unknown>> {
  const cslId = String(args.csl_id ?? "");
  if (!cslId) {
    return { status: "error", error_code: "invalid_input", message: "csl_id is required" };
  }
  const cfg = runtimeConfig();
  const index = await getSearchIndex();
  const rows = index.db.prepare("SELECT id, folder FROM sources").all() as unknown as Array<{
    id: string;
    folder: string;
  }>;
  let source = rows.find((row) => row.id === cslId || row.folder === cslId);

  if (!source) {
    // Fallback for a document present on disk but absent from a stale index.
    for (const entry of readdirSync(cfg.corpusRoot, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue;
      const csl = readJsonFile(path.join(cfg.corpusRoot, entry.name, "csl.json"));
      if (csl?.id === cslId) {
        source = { id: String(csl.id), folder: entry.name };
        break;
      }
    }
  }
  if (!source) {
    return { status: "error", error_code: "not_found", message: `Unknown document: ${cslId}` };
  }

  const corpusDir = realpathSync(path.resolve(cfg.corpusRoot));
  const docDir = path.resolve(cfg.corpusRoot, source.folder);
  if (!existsSync(docDir)) {
    return { status: "error", error_code: "missing_directory", message: docDir };
  }
  const resolvedDocDir = realpathSync(docDir);
  const relative = path.relative(corpusDir, resolvedDocDir);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    return {
      status: "error",
      error_code: "outside_corpus",
      message: `Refusing to delete outside the corpus root: ${resolvedDocDir}`,
    };
  }
  rmSync(resolvedDocDir, { recursive: true, force: false });

  const registryPath = path.join(projectRoot(cfg.corpusRoot), ".shutong", "source-registry.json");
  const registry = readJsonFile(registryPath);
  const removed: string[] = [];
  if (registry && typeof registry === "object") {
    for (const key of Object.keys(registry)) {
      const record = registry[key];
      const documentPath = record && typeof record === "object" ? record.document_path : null;
      let sameDocument = false;
      if (typeof documentPath === "string" && documentPath.trim()) {
        try {
          const candidate = path.isAbsolute(documentPath)
            ? path.resolve(documentPath)
            : path.resolve(projectRoot(cfg.corpusRoot), documentPath);
          sameDocument = realpathSync(candidate) === docDir;
        } catch {
          sameDocument = false;
        }
      }
      if (key === cslId || key === source.id || sameDocument) {
        delete registry[key];
        removed.push(key);
      }
    }
    if (removed.length > 0) {
      writeFileSync(registryPath, `${JSON.stringify(registry, null, 2)}\n`, "utf8");
    }
  }

  index.db.exec("BEGIN IMMEDIATE");
  try {
    index.db
      .prepare("DELETE FROM nodes_fts WHERE rowid IN (SELECT id FROM nodes WHERE source_id=?)")
      .run(source.id);
    index.db.prepare("DELETE FROM nodes WHERE source_id=?").run(source.id);
    index.db.prepare("DELETE FROM sources WHERE id=?").run(source.id);
    index.db.exec("COMMIT");
  } catch (error) {
    index.db.exec("ROLLBACK");
    throw error;
  }

  return {
    status: "ok",
    deleted_path: docDir,
    csl_id: source.id,
    registry_removed: removed,
  };
}
