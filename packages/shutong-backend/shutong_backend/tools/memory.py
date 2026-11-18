"""Memory tools — search, list, save."""

from __future__ import annotations

import asyncio
import os
from typing import Any


async def memory_search(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    from shutong_backend.agents.memory import MemoryStore
    store = MemoryStore(memory_dir=os.path.join(corpus_root, ".memory"))
    entries = await asyncio.to_thread(store.search, args["query"])
    return {
        "status": "ok",
        "results": [entry.to_dict() for entry in entries[: args.get("limit", 20)]],
    }


async def memory_list(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    from shutong_backend.agents.memory import MemoryStore
    store = MemoryStore(memory_dir=os.path.join(corpus_root, ".memory"))
    threads = []
    for thread_id in store._list_threads()[: args.get("limit", 20)]:  # noqa: SLF001
        entries = store.load_thread(thread_id)
        threads.append({
            "thread_id": thread_id,
            "entry_count": len(entries),
            "latest_timestamp": entries[-1].timestamp if entries else None,
            "latest_query": entries[-1].query if entries else None,
        })
    return {"status": "ok", "threads": threads}


async def memory_save(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    from shutong_backend.agents.memory import MemoryStore
    store = MemoryStore(memory_dir=os.path.join(corpus_root, ".memory"))
    entry = await asyncio.to_thread(store.save, "notes", args["title"], args["content"], [])
    return {"status": "ok", "entry": entry.to_dict()}