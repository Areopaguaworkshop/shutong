"""Shutong translation pipeline — EN→ZH-Simplified with mandatory glossary injection.

Public API:
- resolve_source(source, corpus_root) → document dict
- segment_document(doc) → list of translation units
- build_system_prompt(glossary) → system prompt string
- flag_untranslated(zh_text, en_text, glossary) → flagged zh_text
- render_interleaved(doc, units, translated, library_root) → Path
- run(source, glossary_files, corpus_root, library_root, glossary_dir) → result dict
- run_url(url, corpus_root, library_root, glossary_dir) → result dict
- render(csl_id, output_format, library_root) → result dict
"""

from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any

import requests

from shutong_backend.agents.corpus_loader import CorpusLoader

from .glossary import load_all_glossaries, lookup


# ---------------------------------------------------------------------------
# Public: resolve_source (Task 11)
# ---------------------------------------------------------------------------


def resolve_source(source: str, corpus_root: str) -> dict[str, Any]:
    """Resolve a source identifier to a document.

    source can be:
    - A csl_id (e.g., "Smith_2025_Logos") → look up in corpus
    - A file path (e.g., "/path/to/paper.pdf") → read then translate
    - Plain text string → translate directly
    """
    # Try file path first — check if it's an actual file
    source_path = Path(source)
    if source_path.is_file():
        text = source_path.read_text(encoding="utf-8")
        return {
            "source_type": "file",
            "source_id": _slug(source_path.stem),
            "title": source_path.stem,
            "file_path": str(source_path),
            "units": _split_text_units(text),
        }

    # Try csl_id — check if corpus/{source}/ exists
    corpus = Path(corpus_root)
    doc_dir = corpus / source
    if doc_dir.is_dir() and (doc_dir / "document.json").exists():
        try:
            loader = CorpusLoader(corpus_root)
            loader.load()
            source_id = _match_source_id(loader, source)
            if source_id is not None:
                csl = loader.get_csl_by_id(source_id) or loader.get_csl_by_source(source_id) or {}
                return {
                    "source_type": "corpus",
                    "source_id": source_id,
                    "title": csl.get("title", source_id),
                    "document_path": str(doc_dir),
                    "csl_id": source,
                }
        except Exception:
            pass
        # Fallback: directory exists but loader failed — still return corpus type
        return {
            "source_type": "corpus",
            "source_id": source,
            "title": source,
            "document_path": str(doc_dir),
        }

    # Plain text
    return {
        "source_type": "text",
        "source_id": _slug(source[:40] or "inline-text"),
        "title": "Inline text",
        "units": _split_text_units(source),
    }


# ---------------------------------------------------------------------------
# Public: segment_document (Task 12)
# ---------------------------------------------------------------------------


def segment_document(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Segment a document into paragraph-level translation units.

    For corpus documents, reads the PageIndex tree if available.
    Falls back to the document's existing units or text splitting.
    """
    # If the document already has units, use them
    if "units" in doc and doc["units"]:
        return doc["units"]

    # Try reading PageIndex tree from corpus document
    doc_path = doc.get("document_path")
    if doc_path:
        tree_path = Path(doc_path) / "pageindex_tree.json"
        if tree_path.exists():
            try:
                tree = json.loads(tree_path.read_text(encoding="utf-8"))
                units: list[dict[str, Any]] = []
                _walk_tree(tree, units)
                if units:
                    return units
            except (json.JSONDecodeError, OSError):
                pass

        # Fallback: try document.json
        doc_json_path = Path(doc_path) / "document.json"
        if doc_json_path.exists():
            try:
                data = json.loads(doc_json_path.read_text(encoding="utf-8"))
                text = data.get("text", "")
                if text:
                    return _split_text_units(text)
            except (json.JSONDecodeError, OSError):
                pass

    # Final fallback: if doc has raw text
    if doc.get("text"):
        return _split_text_units(doc["text"])

    return []


def _walk_tree(node: dict, units: list[dict[str, Any]]) -> None:
    """Recursively walk PageIndex tree, collecting headings and paragraphs."""
    node_type = node.get("type", "")
    if node_type in ("heading", "section", "chapter"):
        units.append({
            "type": "heading",
            "text": node.get("text", ""),
            "citation": node.get("citation"),
        })
    elif node_type == "paragraph":
        units.append({
            "type": "paragraph",
            "text": node.get("text", ""),
            "citation": node.get("citation"),
        })
    for child in node.get("children", []):
        _walk_tree(child, units)


# ---------------------------------------------------------------------------
# Public: build_system_prompt (Task 13)
# ---------------------------------------------------------------------------


def build_system_prompt(glossary: dict[str, str]) -> str:
    """Build the translation system prompt with mandatory glossary injection.

    Per v4 spec §12: Glossary is pre-injected into the system prompt
    BEFORE the LLM call, never post-hoc.
    """
    if glossary:
        entries = "\n".join(f"- {en} → {zh}" for en, zh in sorted(glossary.items()))
        glossary_block = f"""Mandatory translations (DO NOT override these — they are domain-specific):
{entries}"""
    else:
        glossary_block = "No glossary entries for this document."

    return f"""You are a scholarly EN→ZH-Simplified translator.
Domain: patristic and liturgical scholarship.

{glossary_block}

If a source term matches the glossary, use that translation exactly.
If a proper noun has no glossary entry and no standard Chinese equivalent,
write: [未译: OriginalTerm]

Preserve all citation keys, footnote markers, and section structure.
Output ONLY the translation. No explanations."""


# ---------------------------------------------------------------------------
# Public: flag_untranslated (Task 14)
# ---------------------------------------------------------------------------


def flag_untranslated(zh_text: str, en_text: str, glossary: dict[str, str]) -> str:
    """Flag proper nouns without glossary entries with [未译: ...] markers.

    Per spec §6: Untranslatable proper nouns with no ZH equivalent
    get [未译: OriginalTerm].
    """
    # Find capitalized words in English text that aren't in glossary
    en_words = set(re.findall(r"\b[A-Z][a-zA-Z]+\b", en_text))
    glossary_terms = set(glossary.keys())
    untranslated = en_words - glossary_terms

    # Filter common English words that aren't proper nouns
    common = {
        "The", "This", "That", "These", "Those", "In", "On", "At",
        "To", "For", "Of", "With", "By", "From", "As", "Is", "Are",
        "Was", "Were", "Be", "Been", "Being", "Have", "Has", "Had",
        "Do", "Does", "Did", "Will", "Would", "Could", "Should", "May",
        "Not", "But", "And", "Or", "If", "An", "A", "It", "He", "She",
        "They", "We", "His", "Her", "Its", "Their", "Our", "My",
    }
    untranslated -= common

    # Also filter out glossary terms with different casing
    glossary_lower = {k.lower() for k in glossary_terms}
    untranslated = {t for t in untranslated if t.lower() not in glossary_lower}

    result = zh_text
    for term in sorted(untranslated):
        # Flag terms that weren't translated — they appear as-is in the Chinese text
        # or are entirely missing from it
        result = result.replace(term, f"[未译: {term}]")

    return result


# ---------------------------------------------------------------------------
# Public: render_interleaved (Task 15)
# ---------------------------------------------------------------------------


def render_interleaved(
    doc: dict[str, Any],
    units: list[dict[str, Any]],
    translated: list[str],
    library_root: str,
) -> Path:
    """Render interleaved bilingual Markdown per v4 spec §12.

    Format:
    ---
    title: "Doc Title"
    source: csl_id
    translation: zh-simplified
    date: YYYY-MM-DD
    ---

    ## English Heading / 中文标题

    English paragraph text.

    > 中文翻译段落。

    ---
    """
    library = Path(library_root)
    library.mkdir(parents=True, exist_ok=True)
    source_id = doc.get("source_id", "document")
    output_path = library / f"{source_id}_bilingual.md"

    lines = [
        "---",
        f'title: "{doc.get("title", source_id)}"',
        f"source: {source_id}",
        "translation: zh-simplified",
        f"date: {date.today().isoformat()}",
        "---",
        "",
    ]

    for unit, zh in zip(units, translated):
        if unit.get("type") == "heading":
            lines.append(f"## {unit['text']} / {zh}")
        else:
            lines.append(unit["text"])
            lines.append("")
            lines.append(f"> {zh}")
        lines.append("")
        if unit.get("citation"):
            lines.append(unit["citation"])
            lines.append("")
        lines.append("---")
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


# ---------------------------------------------------------------------------
# Private helpers (kept for backward compat)
# ---------------------------------------------------------------------------


def _match_source_id(loader: CorpusLoader, raw: str) -> str | None:
    for csl in loader.csl_registry:
        if raw in {csl.get("id"), csl.get("_source_id")}:
            return csl.get("_source_id") or csl.get("id")
    return None


def _split_text_units(text: str) -> list[dict[str, str]]:
    parts = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    return [{"text": part, "type": "paragraph", "citation": None} for part in parts]


def _translate_text(text: str, glossary: dict[str, str]) -> str:
    system_prompt = build_system_prompt(glossary)
    response = _ollama_chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]
    )
    return response.strip()


def _ollama_chat(messages: list[dict[str, str]]) -> str:
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    base_url = base_url.rstrip("/")
    model = os.environ.get("SHUTONG_TRANSLATE_MODEL", "glm-5.3-flash:cloud")
    payload = {"model": model.removeprefix("ollama/"), "messages": messages, "stream": False}
    response = requests.post(f"{base_url}/api/chat", json=payload, timeout=600)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("Unexpected Ollama response shape")
    return str(data.get("message", {}).get("content", ""))


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower() or "document"


# ---------------------------------------------------------------------------
# High-level pipeline functions
# ---------------------------------------------------------------------------


def run(
    source: str,
    glossary_files: list[str] | None,
    corpus_root: str,
    library_root: str,
    glossary_dir: str,
) -> dict[str, Any]:
    """Full translation pipeline: resolve → segment → translate → flag → render."""
    doc = resolve_source(source, corpus_root)
    glossary = load_all_glossaries(glossary_dir, extra_files=glossary_files)

    # Segment if not already done
    units = segment_document(doc) if "units" not in doc else doc["units"]

    translated_units: list[str] = []
    glossary_hits: set[str] = set()

    for unit in units:
        text = unit.get("text", "")
        for term in glossary:
            if term in text.lower():
                glossary_hits.add(term)
        translated_units.append(_translate_text(text, glossary))

    # Flag untranslated terms
    untranslated_terms: list[str] = []
    for unit, zh in zip(units, translated_units):
        flagged = flag_untranslated(zh, unit.get("text", ""), glossary)
        # Collect any [未译: ...] markers found
        for match in re.finditer(r"\[未译:\s*(\w+)\]", flagged):
            untranslated_terms.append(match.group(1))

    # Render bilingual output
    output_path = render_interleaved(
        {"source_id": doc.get("source_id", "document"), "title": doc.get("title", "Document")},
        units,
        translated_units,
        library_root,
    )

    return {
        "status": "ok",
        "output_path": str(output_path),
        "sections_translated": len(units),
        "glossary_terms_applied": sorted(glossary_hits),
        "untranslated_terms": sorted(set(untranslated_terms)),
    }


def run_url(url: str, corpus_root: str, library_root: str, glossary_dir: str) -> dict[str, Any]:
    """Ingest a URL and translate it in one step."""
    from citeindex.ingestion.master import CiteIndexIngestionOrchestrator

    orchestrator = CiteIndexIngestionOrchestrator(corpus_root=corpus_root)
    result = orchestrator.ingest(url)
    if result.get("status") != "ok":
        return result
    csl_id = result.get("standardized_csl_json", {}).get("id")
    return run(csl_id or url, None, corpus_root, library_root, glossary_dir)


def render(csl_id: str, output_format: str, library_root: str) -> dict[str, Any]:
    """Return the existing bilingual output path for a translated document."""
    if output_format != "interleaved":
        return {
            "status": "error",
            "error_code": "unsupported_output_format",
            "message": "Only interleaved output is currently implemented.",
        }

    path = Path(library_root) / f"{csl_id}_bilingual.md"
    if not path.exists():
        return {
            "status": "error",
            "error_code": "missing_translation",
            "message": f"No rendered bilingual file found for {csl_id}.",
        }
    return {"status": "ok", "output_path": str(path)}
