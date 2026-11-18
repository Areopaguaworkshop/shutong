"""Corpus tools — status, tree, cite_render, cite_tree."""

from __future__ import annotations

import asyncio
from typing import Any


def _extract_author(csl: dict[str, Any]) -> str:
    authors = csl.get("author") or []
    if not authors:
        return ""
    first = authors[0]
    return first.get("family") or first.get("literal") or ""


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


def _match_source(loader, csl_id: str) -> dict[str, Any] | None:
    for source in loader.sources:
        source_id = source.get("source_id")
        csl = source.get("csl", {})
        if csl_id in {source_id, csl.get("id"), source.get("doc_hash"), source.get("doc_dir")}:
            return source
    return None


def _load_corpus_loader(corpus_root: str):
    from shutong_backend.agents.corpus_loader import CorpusLoader
    loader = CorpusLoader(corpus_root)
    loader.load()
    return loader


async def corpus_status(_args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    loader = await asyncio.to_thread(_load_corpus_loader, corpus_root)
    timestamps = [csl.get("ingestion_timestamp") for csl in loader.csl_registry if csl.get("ingestion_timestamp")]
    docs_with_merkle = sum(1 for source in loader.sources if loader.merkle_registry.get(source.get("source_id", "")))
    return {
        "status": "ok",
        "document_count": len(loader.sources),
        "total_nodes": len(loader.all_nodes),
        "last_ingestion_time": max(timestamps) if timestamps else None,
        "merkle_health": {"documents_with_trees": docs_with_merkle, "documents_missing_trees": len(loader.sources) - docs_with_merkle},
    }


async def corpus_tree(_args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    loader = await asyncio.to_thread(_load_corpus_loader, corpus_root)
    documents = []
    for source in loader.sources:
        source_id = source.get("source_id", "")
        csl = source.get("csl", {})
        documents.append({
            "source_id": source_id,
            "title": csl.get("title", source_id),
            "author": _extract_author(csl),
            "year": (_citation_key(csl).split()[-1] if _citation_key(csl) else ""),
            "node_count": len(loader.get_nodes_by_source(source_id)),
            "document_path": source.get("doc_dir", ""),
        })
    return {"status": "ok", "documents": documents}


async def cite_render(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    from citeindex.citation_style import format_bibliography
    loader = await asyncio.to_thread(_load_corpus_loader, corpus_root)
    source = _match_source(loader, args["csl_id"])
    if source is None:
        return {"status": "error", "error_code": "not_found", "message": f"Unknown document: {args['csl_id']}"}
    bibliography, in_text = format_bibliography([source.get("csl", {})], args.get("style", "chicago-author-date"))
    return {"status": "ok", "bibliography": bibliography, "in_text": in_text}


async def cite_tree(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    loader = await asyncio.to_thread(_load_corpus_loader, corpus_root)
    source = _match_source(loader, args["csl_id"])
    if source is None:
        return {"status": "error", "error_code": "not_found", "message": f"Unknown document: {args['csl_id']}"}
    tree = loader.merkle_registry.get(source.get("source_id", ""), {})
    return {"status": "ok", "csl_id": source.get("source_id", ""), "tree": tree}