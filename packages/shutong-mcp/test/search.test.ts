import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { SearchIndex } from "../src/search/index.ts";

function writeJson(file: string, value: unknown): void {
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, JSON.stringify(value, null, 2), "utf8");
}

function makeCorpus(): string {
  const root = mkdtempSync(path.join(os.tmpdir(), "shutong-search-"));
  writeJson(path.join(root, "doc-a", "csl.json"), {
    id: "src-a",
    title: "中国经济发展",
    author: [{ family: "袁" }],
    issued: { "date-parts": [[2020]] },
    content_hash: "hash-a",
  });
  writeJson(path.join(root, "doc-a", "document.json"), {
    pages: [
      {
        page_number: 1,
        columns: [
          {
            paragraphs: [
              { paragraph_id: "p1_1", text: "中国经济发展" },
              { paragraph_id: "p1_2", text: "theology history" },
            ],
          },
        ],
      },
    ],
  });
  writeJson(path.join(root, "doc-a", "merkle.json"), { root: "a", levels: [["a"]] });

  writeJson(path.join(root, "doc-b", "csl.json"), {
    id: "src-b",
    title: "Theology History",
    author: [{ family: "Smith" }],
    issued: { "date-parts": [[2021]] },
    content_hash: "hash-b",
  });
  writeJson(path.join(root, "doc-b", "document.json"), {
    pages: [
      {
        page_number: 2,
        paragraphs: [
          { paragraph_id: "p2_1", text: "theology history" },
          { paragraph_id: "p2_2", text: "justification by faith" },
        ],
      },
    ],
  });
  writeJson(path.join(root, "doc-b", "merkle.json"), { root: "b", levels: [["b"]] });
  return root;
}

test("SQLite FTS5 indexes Chinese and English nodes", () => {
  const corpus = makeCorpus();
  const dbPath = path.join(corpus, ".index", "search.sqlite");
  const index = new SearchIndex(dbPath);
  try {
    const stats = index.indexCorpus(corpus, { reset: true });
    assert.equal(stats.documents, 2);
    assert.equal(stats.nodes, 4);
    assert.equal(stats.schemaVersion, "1");

    const zh = index.search("中国", { limit: 10 });
    assert.equal(zh.length, 1);
    assert.equal(zh[0].source_id, "src-a");
    assert.match(zh[0].text, /中国经济发展/);

    const en = index.search("theology", { limit: 10 });
    assert.equal(en.length, 2);

    const scoped = index.search("theology", { limit: 10, sourceIds: ["src-b"] });
    assert.equal(scoped.length, 1);
    assert.equal(scoped[0].source_id, "src-b");

    const scopedOut = index.search("中国", { limit: 10, sourceIds: ["src-b"] });
    assert.deepEqual(scopedOut, []);

    const regex = index.regexSearch("经济", { limit: 10 });
    assert.equal(regex.length, 1);
    assert.equal(regex[0].source_id, "src-a");
  } finally {
    index.close();
    rmSync(corpus, { recursive: true, force: true });
  }
});

test("rebuild is idempotent", () => {
  const corpus = makeCorpus();
  const dbPath = path.join(corpus, ".index", "search.sqlite");
  const index = new SearchIndex(dbPath);
  try {
    const first = index.indexCorpus(corpus, { reset: true });
    const second = index.indexCorpus(corpus, { reset: true });
    assert.equal(first.documents, second.documents);
    assert.equal(first.nodes, second.nodes);
    assert.equal(second.nodes, 4);
    assert.equal(index.search("justification", { limit: 10 }).length, 1);
  } finally {
    index.close();
    rmSync(corpus, { recursive: true, force: true });
  }
});
