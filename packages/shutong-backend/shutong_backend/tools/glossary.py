"""Glossary tools — lookup, add, list, load."""

from __future__ import annotations

import asyncio
from typing import Any

from shutong_backend.translation.glossary import add_entry, copy_file, list_all, lookup


async def glossary_lookup(args: dict[str, Any], glossary_dir: str) -> dict[str, Any]:
    return {"status": "ok", "results": await asyncio.to_thread(lookup, args["terms"], glossary_dir)}


async def glossary_add(args: dict[str, Any], glossary_dir: str) -> dict[str, Any]:
    return await asyncio.to_thread(add_entry, args["term_en"], args["term_zh"], glossary_dir, args.get("file"))


async def glossary_list(_args: dict[str, Any], glossary_dir: str) -> dict[str, Any]:
    return {"status": "ok", "files": await asyncio.to_thread(list_all, glossary_dir)}


async def glossary_load(args: dict[str, Any], glossary_dir: str) -> dict[str, Any]:
    return await asyncio.to_thread(copy_file, args["filepath"], glossary_dir)