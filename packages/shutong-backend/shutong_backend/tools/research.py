"""Research tools — search and chat over the local corpus."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from shutong_backend import papers


async def search(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    from shutong_backend.agents.chat import SearchPipeline
    pipeline = SearchPipeline(corpus_root=corpus_root)
    paper_id = papers.resolve_paper_id(args, corpus_root)
    allowed = papers.allowed_source_ids(paper_id, corpus_root) if paper_id else None
    result = await asyncio.to_thread(pipeline.search, args["query"], args.get("top_k", 20), allowed_source_ids=allowed)
    if paper_id:
        result["paper_id"] = paper_id
    return result


async def chat(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    if papers.resolve_paper_id(args, corpus_root):
        from shutong_backend.tools.errors import ShutongError
        raise ShutongError("paper_scope_required", "The legacy chat pipeline cannot enforce paper source membership.", "Use shutong_search while a paper is active.")
    from shutong_backend.agents.chat import ChatPipeline
    from shutong_backend.rpc_server import _llm_model
    pipeline = ChatPipeline(corpus_root=corpus_root, llm_model=_llm_model())
    return await asyncio.to_thread(pipeline.chat, args["query"])


async def regex_search(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    from shutong_backend.agents.corpus_loader import CorpusLoader

    loader = CorpusLoader(corpus_root)
    loader.load()
    paper_id = papers.resolve_paper_id(args, corpus_root)
    allowed = papers.allowed_source_ids(paper_id, corpus_root) if paper_id else None
    pattern = re.compile(args["pattern"], re.IGNORECASE)
    field = args.get("field", "text")
    matches = []
    if field == "text":
        for node in loader.all_nodes:
            if allowed is not None and node.get("source_id") not in allowed:
                continue
            text = node.get("text", "")
            if pattern.search(text):
                matches.append({
                    "source_id": node.get("source_id", ""),
                    "node_id": node.get("node_id", ""),
                    "text": text,
                })
    else:
        for source in loader.sources:
            if allowed is not None and source.get("source_id") not in allowed:
                continue
            csl = source.get("csl", {})
            value = ""
            if field == "title":
                value = csl.get("title", "")
            elif field == "author":
                authors = csl.get("author") or []
                if authors:
                    first = authors[0]
                    value = first.get("family") or first.get("literal") or ""
            elif field == "year":
                issued = csl.get("issued", {}).get("date-parts", [])
                if issued and issued[0]:
                    value = str(issued[0][0])
            if pattern.search(value):
                matches.append({"source_id": source.get("source_id", ""), "value": value})
    return {"status": "ok", "matches": matches, **({"paper_id": paper_id} if paper_id else {})}
