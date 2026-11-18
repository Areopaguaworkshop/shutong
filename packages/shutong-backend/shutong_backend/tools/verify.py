"""Verification tools — Merkle integrity checks and citation resolution."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from shutong_backend.agents.corpus_loader import CorpusLoader


def _match_source(loader: "CorpusLoader", csl_id: str) -> dict[str, Any] | None:
    for source in loader.sources:
        source_id = source.get("source_id")
        csl = source.get("csl", {})
        if csl_id in {source_id, csl.get("id"), source.get("doc_hash"), source.get("doc_dir")}:
            return source
    return None


def _citation_key(csl: dict[str, Any]) -> str:
    authors = csl.get("author") or []
    author = "Unknown"
    if authors:
        first = authors[0]
        author = first.get("family") or first.get("literal") or author
    year = "n.d."
    issued = csl.get("issued", {}).get("date-parts", [])
    if issued and issued[0]:
        year = str(issued[0][0])
    return f"{author} {year}".strip()


def _extract_author(csl: dict[str, Any]) -> str:
    authors = csl.get("author") or []
    if not authors:
        return ""
    first = authors[0]
    return first.get("family") or first.get("literal") or ""


def _verify_document(loader: "CorpusLoader", source: dict[str, Any], node_hash: str | None = None) -> dict[str, Any]:
    from citeindex.ingestion.deterministic import build_merkle_proof, build_merkle_tree, hash_payload, sha256_hex

    source_id = source.get("source_id", "")
    nodes = loader.get_nodes_by_source(source_id)
    merkle = loader.merkle_registry.get(source_id, {})
    leaves = list((merkle.get("levels") or [[]])[0])
    merkle_root = merkle.get("root", "")
    mismatches: list[dict[str, str]] = []

    for node in nodes:
        recomputed = hash_payload(node.get("text", ""))
        if recomputed != node.get("sha256"):
            mismatches.append({
                "node_id": node.get("node_id", ""),
                "reason": "hash_mismatch",
                "expected": node.get("sha256", ""),
                "actual": recomputed,
            })
        if node.get("sha256") not in leaves:
            mismatches.append({
                "node_id": node.get("node_id", ""),
                "reason": "missing_from_merkle_leaves",
                "expected": node.get("sha256", ""),
                "actual": "",
            })

    if leaves:
        rebuilt_root = build_merkle_tree(leaves).get("root", "")
        if rebuilt_root != merkle_root:
            mismatches.append({
                "node_id": source_id,
                "reason": "root_mismatch",
                "expected": merkle_root,
                "actual": rebuilt_root,
            })

    result = {
        "status": "pass" if not mismatches else "fail",
        "csl_id": source_id,
        "nodes_checked": len(nodes),
        "document_merkle_root": merkle_root,
        "mismatches": mismatches,
    }

    if node_hash is None:
        return result

    match = next((node for node in nodes if node.get("sha256") == node_hash), None)
    if match is None:
        result["status"] = "fail"
        result["mismatches"].append({
            "node_id": source_id,
            "reason": "node_hash_not_found",
            "expected": node_hash,
            "actual": "",
        })
        return result

    index = leaves.index(node_hash) if node_hash in leaves else -1
    if index >= 0:
        proof = build_merkle_proof(merkle, index)
        proof_valid = _verify_proof(node_hash, proof, merkle_root)
    else:
        proof = []
        proof_valid = False

    result["node"] = {
        "node_id": match.get("node_id", ""),
        "sha256": node_hash,
        "proof": proof,
        "proof_valid": proof_valid,
    }
    if not proof_valid:
        result["status"] = "fail"
        result["mismatches"].append({
            "node_id": match.get("node_id", ""),
            "reason": "invalid_merkle_proof",
            "expected": merkle_root,
            "actual": "",
        })
    return result


def _verify_proof(leaf_hash: str, proof: list[dict[str, str]], root: str) -> bool:
    from citeindex.ingestion.deterministic import sha256_hex

    current = leaf_hash
    for step in proof:
        sibling = step.get("hash", "")
        if step.get("position") == "left":
            current = sha256_hex(sibling + current)
        else:
            current = sha256_hex(current + sibling)
    return current == root


def _load_corpus_loader(corpus_root: str) -> "CorpusLoader":
    from shutong_backend.agents.corpus_loader import CorpusLoader
    loader = CorpusLoader(corpus_root)
    loader.load()
    return loader


async def verify(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    loader = await asyncio.to_thread(_load_corpus_loader, corpus_root)
    source = _match_source(loader, args["csl_id"])
    if source is None:
        return {"status": "fail", "error_code": "not_found", "message": f"Unknown document: {args['csl_id']}"}
    return _verify_document(loader, source, args.get("node_hash"))


async def verify_all(_args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    loader = await asyncio.to_thread(_load_corpus_loader, corpus_root)
    documents = [_verify_document(loader, source) for source in loader.sources]
    failures = [document for document in documents if document.get("status") != "pass"]
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "documents": documents,
        "failures": len(failures),
    }


async def resolve_citation(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    loader = await asyncio.to_thread(_load_corpus_loader, corpus_root)
    key = args["citation_key"].strip().lower()
    for source in loader.sources:
        csl = source.get("csl", {})
        candidates = {
            str(source.get("source_id", "")).lower(),
            str(csl.get("id", "")).lower(),
            _citation_key(csl).lower(),
        }
        if key in candidates:
            return {
                "status": "ok",
                "source_id": source.get("source_id", ""),
                "title": csl.get("title", ""),
                "document_path": source.get("doc_dir", ""),
                "citation_key": _citation_key(csl),
            }
    return {"status": "error", "error_code": "not_found", "message": f"No citation matches {args['citation_key']}"}