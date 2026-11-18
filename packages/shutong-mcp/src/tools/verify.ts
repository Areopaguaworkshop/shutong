import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import {
  buildMerkleProof,
  buildMerkleTree,
  hashPayload,
  verifyMerkleProof,
  type MerkleTree,
} from "../contract/hash.ts";
import type { SearchIndex } from "../search/index.ts";
import { getSearchIndex, runtimeConfig } from "./context.ts";

interface SourceRow {
  id: string;
  folder: string;
}

interface NodeRow {
  node_id: string;
  text: string;
  sha256: string | null;
}

interface MerkleFile extends MerkleTree {
  hierarchical_root?: string;
  proof_tree?: unknown;
}

function mismatch(
  nodeId: string,
  reason: string,
  expected: string,
  actual: string,
): Record<string, string> {
  return { node_id: nodeId, reason, expected, actual };
}

function readMerkle(corpusRoot: string, folder: string): MerkleFile | null {
  const file = path.join(corpusRoot, folder, "merkle.json");
  if (!existsSync(file)) return null;
  try {
    const value = JSON.parse(readFileSync(file, "utf8")) as MerkleFile;
    return value && Array.isArray(value.levels) && typeof value.root === "string" ? value : null;
  } catch {
    return null;
  }
}

function verifyDocument(
  index: SearchIndex,
  source: SourceRow,
  nodeHash: string | null,
): Record<string, unknown> {
  const cfg = runtimeConfig();
  const nodes = index.db
    .prepare("SELECT node_id, text, sha256 FROM nodes WHERE source_id=? ORDER BY id")
    .all(source.id) as unknown as NodeRow[];
  const merkle = readMerkle(cfg.corpusRoot, source.folder);
  const leaves = Array.isArray(merkle?.levels?.[0]) ? merkle!.levels[0] : [];
  const root = merkle?.root ?? "";
  const mismatches: Array<Record<string, string>> = [];

  if (nodes.length === 0) {
    mismatches.push(mismatch(source.id, "no_nodes", "at least one document node", "0"));
  } else if (!nodes.some((node) => node.text.trim())) {
    mismatches.push(
      mismatch(source.id, "missing_document_content", "at least one non-empty text node", "all nodes empty"),
    );
  }
  if (leaves.length === 0 || !root) {
    mismatches.push(
      mismatch(
        source.id,
        "missing_merkle_evidence",
        "merkle leaves and root",
        `leaves=${leaves.length} root=${JSON.stringify(root)}`,
      ),
    );
  }

  for (const node of nodes) {
    const text = String(node.text ?? "");
    const recomputed = hashPayload(text);
    if (!text.trim()) {
      mismatches.push(mismatch(node.node_id, "missing_document_content", "non-empty node text", "empty"));
    }
    if (recomputed !== node.sha256) {
      mismatches.push(mismatch(node.node_id, "hash_mismatch", node.sha256 ?? "", recomputed));
    }
    if (node.sha256 && !leaves.includes(node.sha256)) {
      mismatches.push(mismatch(node.node_id, "missing_from_merkle_leaves", node.sha256, ""));
    }
  }

  if (leaves.length > 0) {
    const rebuilt = buildMerkleTree(leaves).root;
    if (rebuilt !== root) {
      mismatches.push(mismatch(source.id, "root_mismatch", root, rebuilt));
    }
  }

  const result: Record<string, unknown> = {
    status: mismatches.length === 0 ? "pass" : "fail",
    csl_id: source.id,
    nodes_checked: nodes.length,
    document_merkle_root: root,
    mismatches,
  };
  if (mismatches.length > 0) result.reason = mismatches[0].reason;

  if (nodeHash) {
    const match = nodes.find((node) => node.sha256 === nodeHash);
    if (!match) {
      mismatches.push(mismatch(source.id, "node_hash_not_found", nodeHash, ""));
      result.status = "fail";
      result.reason = "node_hash_not_found";
      return result;
    }
    const leafIndex = leaves.indexOf(nodeHash);
    const tree: MerkleTree = {
      algorithm: "sha256",
      leaf_count: leaves.length,
      levels: merkle!.levels,
      root,
    };
    const proof = leafIndex >= 0 ? buildMerkleProof(tree, leafIndex) : [];
    const valid = leafIndex >= 0 && verifyMerkleProof(nodeHash, proof, root);
    result.node = { node_id: match.node_id, sha256: nodeHash, proof, proof_valid: valid };
    if (!valid) {
      mismatches.push(mismatch(match.node_id, "invalid_merkle_proof", root, ""));
      result.status = "fail";
      result.reason = "invalid_merkle_proof";
    }
  }
  return result;
}

export async function handleVerify(args: {
  csl_id?: string;
  node_hash?: string | null;
  mode?: string;
}): Promise<Record<string, unknown>> {
  const index = await getSearchIndex();
  const sources = index.db.prepare("SELECT id, folder FROM sources").all() as unknown as SourceRow[];

  if ((args.mode ?? "node") === "all") {
    const documents = sources.map((source) => verifyDocument(index, source, null));
    const failures = documents.filter((document) => document.status !== "pass");
    const result: Record<string, unknown> = {
      status: documents.length > 0 && failures.length === 0 ? "ok" : "fail",
      timestamp: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
      documents,
      failures: failures.length,
    };
    if (documents.length === 0) {
      result.mismatches = [mismatch("", "no_documents", "at least one ingested document", "0")];
      result.reason = "no_documents";
    } else if (failures.length > 0) {
      result.reason = (failures[0] as any).reason ?? "integrity_mismatch";
    }
    return result;
  }

  if (!args.csl_id) {
    return {
      status: "fail",
      error_code: "invalid_input",
      message: "csl_id is required when mode=node",
      next_action: "Pass csl_id, or use mode=all.",
    };
  }
  const source = sources.find(
    (candidate) => candidate.id === args.csl_id || candidate.folder === args.csl_id,
  );
  if (!source) {
    return {
      status: "fail",
      error_code: "not_found",
      message: `Unknown document: ${args.csl_id}`,
    };
  }
  return verifyDocument(index, source, args.node_hash ?? null);
}
