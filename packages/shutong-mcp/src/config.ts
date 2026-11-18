import path from "node:path";

export interface RuntimeConfig {
  corpusRoot: string;
  storageDir: string;
  dbPath: string;
}

export function loadRuntimeConfig(): RuntimeConfig {
  const corpusRoot = path.resolve(process.env.SHUTONG_CORPUS_ROOT ?? "corpus");
  const storageDir = path.resolve(process.env.SHUTONG_STORAGE_DIR ?? ".shutong");
  const dbPath = path.resolve(
    process.env.SHUTONG_INDEX_DB ?? path.join(storageDir, "search.sqlite"),
  );
  return { corpusRoot, storageDir, dbPath };
}
