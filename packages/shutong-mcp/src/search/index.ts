import { DatabaseSync } from "node:sqlite";
import { existsSync, mkdirSync, statSync } from "node:fs";
import path from "node:path";
import { listCorpusFolders, loadSource, sha256Hex, type SourceRecord } from "./corpus.ts";
import { ftsQuery } from "./tokenize.ts";

export const SCHEMA_VERSION = 1;

const DDL = `
CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY,
  folder TEXT NOT NULL UNIQUE,
  content_hash TEXT UNIQUE,
  csl_json TEXT NOT NULL,
  title TEXT NOT NULL,
  author_text TEXT,
  year INTEGER,
  doi TEXT,
  url TEXT,
  indexed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sources_title_idx ON sources(title);
CREATE INDEX IF NOT EXISTS sources_doi_idx ON sources(doi);

CREATE TABLE IF NOT EXISTS nodes (
  id INTEGER PRIMARY KEY,
  node_id TEXT NOT NULL,
  source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  page INTEGER,
  para INTEGER,
  text TEXT NOT NULL,
  tokens TEXT NOT NULL,
  sha256 TEXT
);
CREATE INDEX IF NOT EXISTS nodes_source_idx ON nodes(source_id);
CREATE INDEX IF NOT EXISTS nodes_node_id_idx ON nodes(node_id);

CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
  tokens,
  content='',
  contentless_delete=1,
  tokenize='unicode61'
);

CREATE TABLE IF NOT EXISTS index_meta (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at TEXT NOT NULL
);
`;

export interface SearchHit {
  node_id: string;
  source_id: string;
  page: number;
  para: number;
  text: string;
  score: number;
}

export interface SearchOptions {
  limit?: number;
  sourceIds?: string[];
}

export interface IndexStats {
  documents: number;
  nodes: number;
  dbBytes: number;
  schemaVersion: string | null;
  corpusHash: string | null;
  builtAt: string | null;
}

function asNumber(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export class SearchIndex {
  readonly db: DatabaseSync;
  readonly dbPath: string;

  constructor(dbPath: string) {
    this.dbPath = path.resolve(dbPath);
    mkdirSync(path.dirname(this.dbPath), { recursive: true });
    this.db = new DatabaseSync(this.dbPath);
    this.db.exec("PRAGMA journal_mode=WAL");
    this.db.exec("PRAGMA synchronous=NORMAL");
    this.db.exec("PRAGMA foreign_keys=ON");
    this.migrate();
  }

  migrate(): void {
    this.db.exec(DDL);
    this.setMeta("schema_version", String(SCHEMA_VERSION));
  }

  close(): void {
    this.db.close();
  }

  setMeta(key: string, value: string): void {
    this.db
      .prepare(
        "INSERT INTO index_meta(key,value,updated_at) VALUES(?,?,?) " +
          "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
      )
      .run(key, value, new Date().toISOString());
  }

  getMeta(key: string): string | null {
    const row = this.db.prepare("SELECT value FROM index_meta WHERE key=?").get(key) as
      | { value?: string }
      | undefined;
    return row?.value ?? null;
  }

  reset(): void {
    this.db.exec("DELETE FROM nodes_fts");
    this.db.exec("DELETE FROM nodes");
    this.db.exec("DELETE FROM sources");
    this.db.exec("DELETE FROM index_meta");
    this.setMeta("schema_version", String(SCHEMA_VERSION));
  }

  upsertSource(source: SourceRecord): number {
    const now = new Date().toISOString();
    this.db.exec("BEGIN IMMEDIATE");
    try {
      this.db
        .prepare("DELETE FROM nodes_fts WHERE rowid IN (SELECT id FROM nodes WHERE source_id=?)")
        .run(source.id);
      this.db.prepare("DELETE FROM nodes WHERE source_id=?").run(source.id);
      this.db
        .prepare(
          `INSERT INTO sources(id,folder,content_hash,csl_json,title,author_text,year,doi,url,indexed_at)
           VALUES(?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
             folder=excluded.folder, content_hash=excluded.content_hash, csl_json=excluded.csl_json,
             title=excluded.title, author_text=excluded.author_text, year=excluded.year,
             doi=excluded.doi, url=excluded.url, indexed_at=excluded.indexed_at`,
        )
        .run(
          source.id,
          source.folder,
          source.contentHash,
          JSON.stringify(source.csl),
          source.title,
          source.authorText,
          source.year,
          source.doi,
          source.url,
          now,
        );

      const insertNode = this.db.prepare(
        "INSERT INTO nodes(node_id,source_id,page,para,text,tokens,sha256) VALUES(?,?,?,?,?,?,?)",
      );
      const insertFts = this.db.prepare("INSERT INTO nodes_fts(rowid,tokens) VALUES(?,?)");
      for (const node of source.nodes) {
        const result = insertNode.run(
          node.node_id,
          node.source_id,
          node.page,
          node.para,
          node.text,
          node.tokens,
          node.sha256,
        );
        insertFts.run(Number(result.lastInsertRowid), node.tokens);
      }
      this.db.exec("COMMIT");
      return source.nodes.length;
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
  }

  indexCorpus(corpusRoot: string, options: { reset?: boolean } = {}): IndexStats {
    const root = path.resolve(corpusRoot);
    const folders = listCorpusFolders(root);
    if (options.reset ?? true) this.reset();

    let nodes = 0;
    let sources = 0;
    const hashes: string[] = [];
    for (const folder of folders) {
      const source = loadSource(root, folder);
      if (!source) continue;
      sources += 1;
      nodes += this.upsertSource(source);
      hashes.push(`${source.id}:${source.contentHash ?? ""}`);
    }

    const corpusHash = sha256Hex(hashes.sort().join("\n"));
    this.setMeta("corpus_hash", corpusHash);
    this.setMeta("built_at", new Date().toISOString());
    this.setMeta("node_count", String(nodes));
    this.setMeta("source_count", String(sources));
    return this.stats();
  }

  search(query: string, options: SearchOptions = {}): SearchHit[] {
    const match = ftsQuery(query);
    if (!match) return [];
    const limit = Math.max(1, Math.min(1000, asNumber(options.limit, 20)));
    const sourceIds = options.sourceIds?.filter(Boolean) ?? [];
    let sql =
      "SELECT n.node_id, n.source_id, n.page, n.para, n.text, bm25(nodes_fts) AS score " +
      "FROM nodes_fts JOIN nodes n ON n.id = nodes_fts.rowid WHERE nodes_fts MATCH ?";
    const params: Array<string | number> = [match];
    if (options.sourceIds !== undefined && sourceIds.length === 0) return [];
    if (sourceIds.length > 0) {
      sql += ` AND n.source_id IN (${sourceIds.map(() => "?").join(",")})`;
      params.push(...sourceIds);
    }
    sql += " ORDER BY score, n.id LIMIT ?";
    params.push(limit);
    return this.db.prepare(sql).all(...params).map((row: any) => ({
      node_id: String(row.node_id),
      source_id: String(row.source_id),
      page: asNumber(row.page),
      para: asNumber(row.para),
      text: String(row.text),
      score: asNumber(row.score),
    }));
  }

  regexSearch(pattern: string, options: SearchOptions = {}): SearchHit[] {
    const limit = Math.max(1, Math.min(1000, asNumber(options.limit, 100)));
    const sourceIds = options.sourceIds?.filter(Boolean) ?? [];
    let regexp: RegExp;
    try {
      regexp = new RegExp(pattern, "u");
    } catch (error) {
      throw new Error(`Invalid regular expression: ${(error as Error).message}`);
    }
    this.db.function("regexp", (candidate: unknown, value: unknown) =>
      regexp.test(String(value)) ? 1 : 0,
    );
    let sql = "SELECT node_id, source_id, page, para, text, 0 AS score FROM nodes WHERE regexp(?, text)";
    const params: Array<string | number> = [pattern];
    if (options.sourceIds !== undefined && sourceIds.length === 0) return [];
    if (sourceIds.length > 0) {
      sql += ` AND source_id IN (${sourceIds.map(() => "?").join(",")})`;
      params.push(...sourceIds);
    }
    sql += " LIMIT ?";
    params.push(limit);
    return this.db.prepare(sql).all(...params).map((row: any) => ({
      node_id: String(row.node_id),
      source_id: String(row.source_id),
      page: asNumber(row.page),
      para: asNumber(row.para),
      text: String(row.text),
      score: 0,
    }));
  }

  stats(): IndexStats {
    const documents = this.db.prepare("SELECT count(*) AS c FROM sources").get() as { c: number };
    const nodes = this.db.prepare("SELECT count(*) AS c FROM nodes").get() as { c: number };
    let dbBytes = 0;
    for (const suffix of ["", "-wal", "-shm"]) {
      const file = `${this.dbPath}${suffix}`;
      if (existsSync(file)) dbBytes += statSync(file).size;
    }
    return {
      documents: asNumber(documents.c),
      nodes: asNumber(nodes.c),
      dbBytes,
      schemaVersion: this.getMeta("schema_version"),
      corpusHash: this.getMeta("corpus_hash"),
      builtAt: this.getMeta("built_at"),
    };
  }
}
