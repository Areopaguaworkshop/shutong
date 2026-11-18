"""Translation tools — translate, translate_url, render_bilingual."""

from __future__ import annotations

import asyncio
from typing import Any

from shutong_backend.translation import render as render_translation
from shutong_backend.translation import run as run_translation
from shutong_backend.translation import run_url as run_translation_url


async def translate(args: dict[str, Any], corpus_root: str, library_root: str, glossary_dir: str) -> dict[str, Any]:
    return await asyncio.to_thread(
        run_translation,
        args["source"],
        args.get("glossary_files"),
        corpus_root,
        library_root,
        glossary_dir,
    )


async def translate_url(args: dict[str, Any], corpus_root: str, library_root: str, glossary_dir: str) -> dict[str, Any]:
    return await asyncio.to_thread(run_translation_url, args["url"], corpus_root, library_root, glossary_dir)


async def render_bilingual(args: dict[str, Any], library_root: str) -> dict[str, Any]:
    return await asyncio.to_thread(render_translation, args["csl_id"], args.get("output_format", "interleaved"), library_root)