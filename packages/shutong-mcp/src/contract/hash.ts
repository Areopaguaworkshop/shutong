import { createHash } from "node:crypto";
import { canonicalizeText } from "../search/tokenize.ts";

export interface MerkleTree {
  algorithm: "sha256";
  leaf_count: number;
  levels: string[][];
  root: string;
}

export interface MerkleProofStep {
  position: "left" | "right";
  hash: string;
}

export function sha256Hex(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

/** Compare strings by Unicode code point, not UTF-16 code unit. */
function compareCodePoints(left: string, right: string): number {
  const a = Array.from(left, (char) => char.codePointAt(0)!);
  const b = Array.from(right, (char) => char.codePointAt(0)!);
  const length = Math.min(a.length, b.length);
  for (let index = 0; index < length; index += 1) {
    if (a[index] !== b[index]) return a[index] - b[index];
  }
  return a.length - b.length;
}

/**
 * A compact Python-json.dumps-compatible serializer for the payload shapes
 * citeindex persists (strings, ints, booleans, nulls, arrays, objects).
 *
 * Floats are best-effort: JSON.parse cannot distinguish 1 from 1.0, and
 * Python's exponent formatting differs from JavaScript's. The current
 * citeindex artifacts use integers, so the contract tests cover those.
 */
export function canonicalJsonDumps(value: unknown): string {
  return serialize(value, ",", ":");
}

/** Python json.dumps default separators; used by analysis._digest. */
export function pythonJsonDumpsSpaced(value: unknown): string {
  return serialize(value, ", ", ": ");
}

function serialize(value: unknown, comma: string, colon: string): string {
  if (value === null) return "null";
  if (value === undefined) return "null";
  switch (typeof value) {
    case "string":
      return JSON.stringify(value);
    case "number":
      if (Number.isNaN(value)) return "NaN";
      if (value === Infinity) return "Infinity";
      if (value === -Infinity) return "-Infinity";
      return String(value);
    case "boolean":
      return value ? "true" : "false";
    case "bigint":
      return String(value);
    case "object": {
      if (Array.isArray(value)) {
        return `[${value.map((item) => serialize(item, comma, colon)).join(comma)}]`;
      }
      const record = value as Record<string, unknown>;
      const keys = Object.keys(record)
        .filter((key) => record[key] !== undefined)
        .sort(compareCodePoints);
      return `{${keys
        .map((key) => `${JSON.stringify(key)}${colon}${serialize(record[key], comma, colon)}`)
        .join(comma)}}`;
    }
    default:
      return "null";
  }
}

/** Mirror of citeindex.ingestion.deterministic.hash_payload. */
export function hashPayload(payload: unknown): string {
  const normalized =
    typeof payload === "string" ? canonicalizeText(payload) : canonicalJsonDumps(payload);
  return sha256Hex(normalized);
}

/** Mirror of citeindex.ingestion.deterministic.build_merkle_tree. */
export function buildMerkleTree(leafHashes: string[]): MerkleTree {
  const leaves = leafHashes.length > 0 ? [...leafHashes] : [sha256Hex("")];
  const levels: string[][] = [leaves];
  while (levels[levels.length - 1].length > 1) {
    const current = levels[levels.length - 1];
    const next: string[] = [];
    for (let index = 0; index < current.length; index += 2) {
      const left = current[index];
      const right = index + 1 < current.length ? current[index + 1] : left;
      next.push(sha256Hex(left + right));
    }
    levels.push(next);
  }
  return {
    algorithm: "sha256",
    leaf_count: leaves.length,
    levels,
    root: levels[levels.length - 1][0],
  };
}

/** Mirror of citeindex.ingestion.deterministic.build_merkle_proof. */
export function buildMerkleProof(tree: MerkleTree, leafIndex: number): MerkleProofStep[] {
  const levels = tree.levels;
  if (levels.length === 0 || leafIndex < 0 || leafIndex >= levels[0].length) return [];
  const proof: MerkleProofStep[] = [];
  let index = leafIndex;
  for (const level of levels.slice(0, -1)) {
    let sibling = index ^ 1;
    if (sibling >= level.length) sibling = index;
    proof.push({ position: sibling > index ? "right" : "left", hash: level[sibling] });
    index = Math.floor(index / 2);
  }
  return proof;
}

export function verifyMerkleProof(
  leafHash: string,
  proof: MerkleProofStep[],
  root: string,
): boolean {
  let current = leafHash;
  for (const step of proof) {
    current = step.position === "left" ? sha256Hex(step.hash + current) : sha256Hex(current + step.hash);
  }
  return current === root;
}
