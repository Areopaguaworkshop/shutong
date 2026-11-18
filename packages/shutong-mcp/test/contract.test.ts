import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import {
  buildMerkleProof,
  buildMerkleTree,
  canonicalJsonDumps,
  hashPayload,
  pythonJsonDumpsSpaced,
  verifyMerkleProof,
} from "../src/contract/hash.ts";
import { canonicalizeText } from "../src/search/tokenize.ts";

interface Fixtures {
  canonicalize: Array<{ input: string; expected: string }>;
  json: Array<{ input: unknown; expected: string }>;
  hashPayload: Array<{ input: unknown; expected: string }>;
  merkle: Array<{ leaves: string[]; expected: ReturnType<typeof buildMerkleTree> }>;
  proof: Array<{
    leaves: string[];
    leafIndex: number;
    expected: ReturnType<typeof buildMerkleProof>;
  }>;
}

const fixtures = JSON.parse(
  readFileSync(new URL("./fixtures/merkle-golden.json", import.meta.url), "utf8"),
) as Fixtures;

test("canonicalizeText matches Python canonicalize_text", () => {
  for (const entry of fixtures.canonicalize) {
    assert.equal(canonicalizeText(entry.input), entry.expected, JSON.stringify(entry.input));
  }
});

test("canonicalJsonDumps matches Python compact, sorted JSON", () => {
  for (const entry of fixtures.json) {
    assert.equal(canonicalJsonDumps(entry.input), entry.expected, JSON.stringify(entry.input));
  }
});

test("pythonJsonDumpsSpaced matches Python json.dumps default separators", () => {
  assert.equal(pythonJsonDumpsSpaced({ b: 2, a: 1 }), '{"a": 1, "b": 2}');
  assert.equal(
    pythonJsonDumpsSpaced({ nested: [1, "x", true] }),
    '{"nested": [1, "x", true]}',
  );
});

test("hashPayload matches Python hash_payload", () => {
  for (const entry of fixtures.hashPayload) {
    assert.equal(hashPayload(entry.input), entry.expected, JSON.stringify(entry.input));
  }
});

test("buildMerkleTree matches Python build_merkle_tree", () => {
  for (const entry of fixtures.merkle) {
    assert.deepEqual(buildMerkleTree(entry.leaves), entry.expected);
  }
});

test("buildMerkleProof matches Python build_merkle_proof", () => {
  for (const entry of fixtures.proof) {
    const tree = buildMerkleTree(entry.leaves);
    const proof = buildMerkleProof(tree, entry.leafIndex);
    assert.deepEqual(proof, entry.expected);
    assert.equal(verifyMerkleProof(tree.levels[0][entry.leafIndex], proof, tree.root), true);
  }
});

test("real corpus merkle roots rebuild byte-identically", () => {
  const corpus = process.env.SHUTONG_CORPUS ?? path.resolve(import.meta.dirname, "../../../corpus");
  if (!existsSync(corpus)) return;
  let checked = 0;
  for (const folder of readdirSync(corpus, { withFileTypes: true })) {
    if (!folder.isDirectory()) continue;
    const file = path.join(corpus, folder.name, "merkle.json");
    if (!existsSync(file)) continue;
    const merkle = JSON.parse(readFileSync(file, "utf8")) as {
      leaf_count?: number;
      levels?: string[][];
      root?: string;
    };
    if (!Array.isArray(merkle.levels) || !merkle.levels[0] || typeof merkle.root !== "string") continue;
    const rebuilt = buildMerkleTree(merkle.levels[0]);
    assert.equal(rebuilt.root, merkle.root, folder.name);
    assert.equal(rebuilt.leaf_count, merkle.leaf_count ?? merkle.levels[0].length, folder.name);
    checked += 1;
  }
  assert.ok(checked > 0, "expected at least one real merkle.json fixture");
});
