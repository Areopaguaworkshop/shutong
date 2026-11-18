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

    # Fail closed: a document with no content is unverifiable, not healthy.
    if not nodes:
        mismatches.append({
            "node_id": source_id,
            "reason": "no_nodes",
            "expected": "at least one document node",
            "actual": "0",
        })
    elif not any(str(node.get("text", "")).strip() for node in nodes):
        mismatches.append({
            "node_id": source_id,
            "reason": "missing_document_content",
            "expected": "at least one non-empty text node",
            "actual": "all nodes empty",
        })
    if not leaves or not merkle_root:
        mismatches.append({
            "node_id": source_id,
            "reason": "missing_merkle_evidence",
            "expected": "merkle leaves and root",
            "actual": f"leaves={len(leaves)} root={merkle_root!r}",
        })

    for node in nodes:
        text = str(node.get("text", ""))
        recomputed = hash_payload(text)
        if not text.strip():
            mismatches.append({
                "node_id": node.get("node_id", ""),
                "reason": "missing_document_content",
                "expected": "non-empty node text",
                "actual": "empty",
            })
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
        return _with_reason(result)

    match = next((node for node in nodes if node.get("sha256") == node_hash), None)
    if match is None:
        result["status"] = "fail"
        result["mismatches"].append({
            "node_id": source_id,
            "reason": "node_hash_not_found",
            "expected": node_hash,
            "actual": "",
        })
        return _with_reason(result)

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
    return _with_reason(result)


def _with_reason(result: dict[str, Any]) -> dict[str, Any]:
    """Attach the first mismatch reason so a fail is legible without parsing."""
    mismatches = result.get("mismatches") or []
    if mismatches:
        result["reason"] = mismatches[0]["reason"]
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
    result: dict[str, Any] = {
        "status": "ok" if documents and not failures else "fail",
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "documents": documents,
        "failures": len(failures),
    }
    if not documents:
        # An empty corpus has no integrity evidence at all; do not report health.
        result["mismatches"] = [{
            "node_id": "",
            "reason": "no_documents",
            "expected": "at least one ingested document",
            "actual": "0",
        }]
        result["reason"] = "no_documents"
    elif failures:
        result["reason"] = failures[0].get("reason", "integrity_mismatch")
    return result


async def resolve_citation(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    loader = await asyncio.to_thread(_load_corpus_loader, corpus_root)
    key = args["citation_key"].strip().lower()
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in loader.sources:
        csl = source.get("csl", {})
        candidates = {
            str(source.get("source_id", "")).lower(),
            str(csl.get("id", "")).lower(),
            _citation_key(csl).lower(),
        }
        if key not in candidates:
            continue
        source_id = str(source.get("source_id", ""))
        if source_id in seen:
            continue
        seen.add(source_id)
        matches.append({
            "source_id": source_id,
            "title": csl.get("title", ""),
            "document_path": source.get("doc_dir", ""),
            "citation_key": _citation_key(csl),
        })
    if len(matches) == 1:
        return {"status": "ok", **matches[0]}
    if len(matches) > 1:
        # Author-year keys are not unique, so never pick one silently.
        return {
            "status": "ambiguous",
            "error_code": "ambiguous_citation",
            "message": f"{len(matches)} documents match {args['citation_key']}; resolve by source id instead.",
            "candidates": matches,
        }
    return {"status": "error", "error_code": "not_found", "message": f"No citation matches {args['citation_key']}"}