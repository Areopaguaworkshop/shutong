#!/usr/bin/env python3
"""
export_vault.py — Convert citeindex corpus JSON into nb-style wiki Markdown files.

Usage:
  python3 export_vault.py --corpus-root ./corpus --wiki-root ./wiki [--llm ollama/qwen3.5:cloud] [--verbose] [--dry-run]

Reads each document subdirectory in the corpus, extracts metadata from csl.json,
document.json, merkle.json (and optionally ingestion_output.json / pageindex_tree.json),
then writes structured Markdown files into the wiki vault.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IMAGE_EXTS = {".png", ".jpeg", ".jpg", ".jpx", ".jp2", ".tiff", ".tif", ".gif", ".bmp"}
TODAY = time.strftime("%Y-%m-%d")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def slug(text: str) -> str:
    """Lowercase, hyphenated slug from arbitrary text. Safe for filenames."""
    text = text.strip().lower()
    # Remove characters unsafe for filenames / wiki-links
    text = re.sub(r"[\"'`”“‘’]", "", text)  # Remove quotes entirely
    text = re.sub(r"[\s_/\\:;,.!?()\[\]{}<>|*^~#@$%&+=「」『』【】（）＝＋]", "-", text)
    # Collapse multiple hyphens
    text = re.sub(r"-{2,}", "-", text)
    text = text.strip("-")
    # Truncate to reasonable length
    if len(text) > 80:
        text = text[:80].rstrip("-")
    return text or "untitled"


def author_slug(author: dict) -> str:
    """Generate slug from CSL author dict. Handles family, given, suffix."""
    parts = []
    family = author.get("family", "")
    given = author.get("given", "")
    suffix = author.get("suffix", "")
    if family:
        parts.append(family)
    if given:
        parts.append(given)
    if not parts and suffix:
        # Fallback: use suffix (stripped of brackets)
        clean = re.sub(r"[【】\[\]()]", "", suffix)
        parts.append(clean)
    return slug(" ".join(parts)) if parts else "unknown-author"


def author_display_name(author: dict) -> str:
    """Display name from CSL author dict."""
    given = author.get("given", "")
    family = author.get("family", "")
    if given and family:
        return f"{given} {family}"
    if family:
        return family
    suffix = author.get("suffix", "")
    if suffix:
        return re.sub(r"[【】\[\]()]", "", suffix)
    return "Unknown"


def format_chicago_citation(csl: dict) -> str:
    """Format a Chicago author-date citation string from CSL-JSON fields."""
    authors = csl.get("author", [])
    # Extract year from CSL issued date-parts
    issued_raw = csl.get("issued", [])
    if isinstance(issued_raw, dict):
        year_parts = issued_raw.get("date-parts", [[]])
    elif isinstance(issued_raw, list) and issued_raw and isinstance(issued_raw[0], list):
        year_parts = issued_raw
    else:
        year_parts = csl.get("date-parts", [[]])
    year = ""
    try:
        if year_parts and year_parts[0]:
            year = str(year_parts[0][0])
    except (IndexError, KeyError, TypeError):
        year = ""
    title = csl.get("title", "Untitled")
    publisher = csl.get("publisher", "")
    doi = csl.get("DOI", "")

    # Author string
    if not authors:
        author_str = "Unknown"
    elif len(authors) == 1:
        a = authors[0]
        family = a.get("family", "")
        given = a.get("given", "")
        if given and family:
            author_str = f"{family}, {given}"
        elif family:
            author_str = family
        else:
            author_str = author_display_name(a)
    elif len(authors) == 2:
        a1, a2 = authors[0], authors[1]
        f1 = a1.get("family", author_display_name(a1))
        g1 = a1.get("given", "")
        f2 = a2.get("family", author_display_name(a2))
        g2 = a2.get("given", "")
        first = f"{f1}, {g1}" if g1 else f1
        second = f"{g2} {f2}" if g2 else f2
        author_str = f"{first}, and {second}"
    else:
        parts = []
        for i, a in enumerate(authors):
            f = a.get("family", author_display_name(a))
            g = a.get("given", "")
            if i < len(authors) - 1:
                parts.append(f"{f}, {g}" if g else f)
            else:
                parts.append(f"and {g} {f}" if g else f"and {f}")
        author_str = ", ".join(parts[:-1]) + " " + parts[-1] if len(parts) > 1 else parts[0]

    # Title
    title_str = f"*{title}*"

    # Publisher
    pub_str = f". {publisher}" if publisher else ""

    # DOI
    doi_str = f". https://doi.org/{doi}" if doi else ""

    return f"{author_str}. {year}. {title_str}{pub_str}{doi_str}"


def read_frontmatter(filepath: Path) -> Optional[dict]:
    """Read YAML frontmatter from a Markdown file. Returns dict or None."""
    if not filepath.exists():
        return None
    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception:
        return None
    if not text.startswith("---"):
        return None
    end = text.find("---", 3)
    if end < 0:
        return None
    fm_text = text[3:end].strip()
    # Minimal YAML parser for flat key-value + lists
    result = {}
    current_key = None
    current_list = None
    for line in fm_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # List item
        if stripped.startswith("- ") and current_key and current_list is not None:
            item = stripped[2:].strip().strip('"').strip("'")
            current_list.append(item)
            continue
        # Key-value
        m = re.match(r"^(\w[\w-]*):\s*(.*)", stripped)
        if m:
            # Save previous list
            if current_key and current_list is not None:
                result[current_key] = current_list
            current_key = m.group(1)
            val = m.group(2).strip().strip('"').strip("'")
            if val:
                result[current_key] = val
                current_list = None
            else:
                current_list = []
        # Bracket list on one line
        elif current_key and current_list is not None:
            bracket_match = re.match(r"^\[(.+)\]$", stripped)
            if bracket_match:
                items = [x.strip().strip('"').strip("'") for x in bracket_match.group(1).split(",")]
                current_list = items
    # Save last
    if current_key and current_list is not None:
        result[current_key] = current_list
    return result if result else None


def wiki_link(category: str, slug_val: str) -> str:
    """Generate a wiki-link string like [[entities/fabrizio-pregadio]]."""
    return f"[[{category}/{slug_val}]]"


def ensure_dir(path: Path) -> None:
    """Create directory if it doesn't exist."""
    path.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Corpus scanning
# ---------------------------------------------------------------------------


def scan_corpus(corpus_root: Path) -> list[Path]:
    """Return sorted list of document subdirectories."""
    dirs = []
    for child in sorted(corpus_root.iterdir()):
        if not child.is_dir():
            continue
        if (child / "csl.json").exists():
            dirs.append(child)
    return dirs


def load_doc_data(doc_dir: Path) -> Optional[dict]:
    """Load all relevant JSON files for a document directory."""
    csl_path = doc_dir / "csl.json"
    doc_path = doc_dir / "document.json"
    merkle_path = doc_dir / "merkle.json"
    ingestion_path = doc_dir / "ingestion_output.json"
    pageindex_path = doc_dir / "pageindex_tree.json"

    if not csl_path.exists():
        return None

    with open(csl_path, encoding="utf-8") as f:
        csl = json.load(f)

    document = None
    if doc_path.exists():
        with open(doc_path, encoding="utf-8") as f:
            document = json.load(f)

    merkle = None
    if merkle_path.exists():
        with open(merkle_path, encoding="utf-8") as f:
            merkle = json.load(f)

    ingestion = None
    if ingestion_path.exists():
        with open(ingestion_path, encoding="utf-8") as f:
            ingestion = json.load(f)

    pageindex = None
    if pageindex_path.exists():
        with open(pageindex_path, encoding="utf-8") as f:
            pageindex = json.load(f)

    # Determine source_id from csl and directory name
    source_id = doc_dir.name

    merkle_root = (
        csl.get("merkle_root", "")
        or (merkle.get("hierarchical_root", "") if merkle else "")
    )

    # Page count from document.json metadata
    page_count = 0
    if document and "metadata" in document:
        page_count = document["metadata"].get("page_count", 0)

    # Extract section paths / headings
    section_paths = set()
    section_tree = []
    if document:
        for node in document.get("nodes", []):
            sp = node.get("section_path", "")
            if sp:
                section_paths.add(sp)
    if ingestion:
        sub = ingestion.get("sub_pipeline_outputs", {})
        doc_sub = sub.get("document_json", {})
        st = doc_sub.get("structure", {}).get("section_tree", [])
        if st:
            section_tree = st
    if pageindex:
        l1 = pageindex.get("level_1", [])
        if l1:
            for entry in l1:
                heading = entry.get("heading")
                if heading:
                    section_tree.append({"heading": heading, "children": entry.get("children", [])})

    # Images
    image_dir = doc_dir / "images"
    images = []
    if image_dir.is_dir():
        for img in sorted(image_dir.iterdir()):
            if img.is_file() and img.suffix.lower() in IMAGE_EXTS:
                images.append(img)

    # First text from document nodes
    first_text = ""
    if document:
        for node in document.get("nodes", []):
            text = node.get("text", "").strip()
            if text and len(text) > 20 and not text.startswith("———"):
                first_text = text
                break

    return {
        "source_id": source_id,
        "csl": csl,
        "document": document,
        "merkle": merkle,
        "merkle_root": merkle_root,
        "page_count": page_count,
        "section_paths": section_paths,
        "section_tree": section_tree,
        "images": images,
        "first_text": first_text,
    }


# ---------------------------------------------------------------------------
# Concept extraction
# ---------------------------------------------------------------------------

# Well-known Daoism concepts to detect in section headings/paths
KNOWN_CONCEPTS = {
    "neidan": {"title": "Neidan (內丹, Internal Alchemy)", "aliases": ["neidan", "internal alchemy"]},
    "waidan": {"title": "Waidan (外丹, External Alchemy)", "aliases": ["waidan", "external alchemy"]},
    "cantong-qi": {"title": "Cantong qi (參同契, The Seal of the Unity of the Three)", "aliases": ["cantong qi", "cantongqi", "seal of the unity"]},
    "wuzhen-pian": {"title": "Wuzhen pian (悟真篇, Awakenong to Reality)", "aliases": ["wuzhen pian", "wuzhenpian", "awakening to reality"]},
    "golden-elixir": {"title": "Golden Elixir (金丹, Jindan)", "aliases": ["golden elixir", "jindan", "金丹"]},
    "jing-qi-shen": {"title": "Jing, Qi, Shen (精氣神, Essence, Breath, Spirit)", "aliases": ["jing qi shen", "essence breath spirit", "three treasures"]},
    "cinnabar-field": {"title": "Cinnabar Field (丹田, Dantian)", "aliases": ["cinnabar field", "dantian", "丹田"]},
    "yin-yang": {"title": "Yin-Yang (陰陽)", "aliases": ["yin yang", "陰陽"]},
    "fire-phases": {"title": "Fire Phases (火候, Huohou)", "aliases": ["fire phases", "huohou", "火候"]},
    "xing-ming": {"title": "Xing and Ming (性命, Nature and Destiny)", "aliases": ["xing and ming", "xing ming", "性命", "nature and destiny"]},
    "inversion": {"title": "Inversion (顛倒, Diandao)", "aliases": ["inversion", "顛倒", "diandao"]},
    "daoism": {"title": "Daoism / Taoism", "aliases": ["daoism", "taoism", "道教"]},
    "healing-exercises": {"title": "Healing Exercises (導引, Daoyin)", "aliases": ["healing exercises", "daoyin", "導引"]},
}

# Section heading keywords → concept slug mapping
KEYWORD_TO_CONCEPT: dict[str, str] = {}
for cslug, cdata in KNOWN_CONCEPTS.items():
    for alias in cdata["aliases"]:
        KEYWORD_TO_CONCEPT[alias.lower()] = cslug


def extract_concepts_from_sections(
    all_doc_data: list[dict],
) -> dict[str, dict]:
    """
    Extract concepts from section headings across all documents.
    Returns dict: concept_slug -> {title, aliases, sources: set(source_id), related: set(concept_slug)}
    """
    concepts: dict[str, dict] = {}

    for doc in all_doc_data:
        source_id = doc["source_id"]
        # Collect all headings from section_tree
        headings = []
        for section in doc.get("section_tree", []):
            h = section.get("heading")
            if h:
                headings.append(h)
            for child in section.get("children", []):
                ch = child.get("heading")
                if ch:
                    headings.append(ch)

        # Also look at section_paths for non-page-number paths
        for sp in doc.get("section_paths", set()):
            if not re.match(r"^p\d+$", sp):
                headings.append(sp.replace("-", " ").replace("_", " "))

        for heading in headings:
            h_lower = heading.lower()
            matched = set()
            for keyword, cslug in KEYWORD_TO_CONCEPT.items():
                if keyword in h_lower:
                    matched.add(cslug)

            # If no known concept matched, try to create one from the heading
            if not matched and len(heading) > 3 and len(heading) < 80:
                # Use the heading itself as a potential concept
                h_slug = slug(heading)
                if h_slug and h_slug not in concepts and len(h_slug) > 2:
                    if h_slug not in KNOWN_CONCEPTS:
                        # Only add if heading appears substantial
                        # (not just generic words like "Introduction", "Preface")
                        skip_words = {
                            "introduction", "preface", "foreword", "contents",
                            "copyright", "notes", "bibliography", "index",
                            "appendix", "glossary", "references", "acknowledgments",
                            "conclusion", "further-readings", "tables",
                            "part-1-introduction", "part-2", "part-3-conclusion",
                            "part-3", "section-10", "works-cited",
                            "glossary-of-chinese-characters",
                            "liu-yiming", "the-five-schools", "the-wu-liu-branch",
                            "golden-elixir-press",
                        }
                        if h_slug not in skip_words and h_lower not in skip_words:
                            concepts.setdefault(h_slug, {
                                "title": heading,
                                "aliases": [h_lower],
                                "sources": set(),
                                "related": set(),
                            })
                            concepts[h_slug]["sources"].add(source_id)

            for cslug in matched:
                if cslug not in concepts:
                    concepts[cslug] = {
                        "title": KNOWN_CONCEPTS[cslug]["title"],
                        "aliases": list(KNOWN_CONCEPTS[cslug]["aliases"]),
                        "sources": set(),
                        "related": set(),
                    }
                concepts[cslug]["sources"].add(source_id)

    # Add cross-relations between concepts that share sources
    concept_slugs = list(concepts.keys())
    for i, c1 in enumerate(concept_slugs):
        for c2 in concept_slugs[i + 1:]:
            shared = concepts[c1]["sources"] & concepts[c2]["sources"]
            if shared:
                concepts[c1]["related"].add(c2)
                concepts[c2]["related"].add(c1)

    return concepts


# ---------------------------------------------------------------------------
# LLM-based topic clustering
# ---------------------------------------------------------------------------


def llm_cluster_topics(
    all_doc_data: list[dict], model: str, verbose: bool = False
) -> dict[str, dict]:
    """Use Ollama to identify 10-20 research topics from titles and section headings."""
    try:
        import requests
    except ImportError:
        print("WARNING: requests library not available, skipping LLM clustering", file=sys.stderr)
        return {}

    # Collect titles and section headings
    items = []
    for doc in all_doc_data:
        csl = doc["csl"]
        title = csl.get("title", "")
        section_headings = []
        for section in doc.get("section_tree", []):
            h = section.get("heading", "")
            if h:
                section_headings.append(h)
            for child in section.get("children", []):
                ch = child.get("heading", "")
                if ch:
                    section_headings.append(ch)
        items.append({"title": title, "sections": section_headings[:30]})

    prompt = (
        "You are a research taxonomy assistant. Given the following academic documents "
        "with their section headings, identify 10-20 research topics that best cluster "
        "these works. Return ONLY a JSON array of objects with keys: "
        '"topic" (string), "slug" (lowercase-hyphenated), "sources" (array of document indices, 0-based).'
        "\n\nDocuments:\n"
    )
    for i, item in enumerate(items):
        secs = "; ".join(item["sections"][:15]) if item["sections"] else "(no sections)"
        prompt += f"\n[{i}] {item['title']} — Sections: {secs}"

    prompt += "\n\nReturn the JSON array:"

    if verbose:
        print(f"  Sending LLM clustering request to {model}...")

    try:
        resp = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            },
            timeout=120,
        )
        resp.raise_for_status()
        result = resp.json()
        raw = result.get("response", "")
        # Parse the JSON from the response
        # The model may return the array directly or wrapped in other text
        # Try to find a JSON array in the response
        bracket_start = raw.find("[")
        bracket_end = raw.rfind("]")
        if bracket_start >= 0 and bracket_end > bracket_start:
            topics_json = json.loads(raw[bracket_start : bracket_end + 1])
        else:
            topics_json = json.loads(raw)

        topics = {}
        for t in topics_json:
            tslug = t.get("slug", slug(t.get("topic", "unknown")))
            source_indices = t.get("sources", [])
            source_ids = []
            for idx in source_indices:
                if 0 <= idx < len(all_doc_data):
                    source_ids.append(all_doc_data[idx]["source_id"])
            topics[tslug] = {
                "title": t.get("topic", tslug),
                "sources": set(source_ids),
                "concepts": set(),
            }

        if verbose:
            print(f"  LLM identified {len(topics)} topics")

        return topics

    except Exception as e:
        print(f"WARNING: LLM clustering failed: {e}", file=sys.stderr)
        return {}


def build_topics_from_frequency(
    concepts: dict[str, dict], min_sources: int = 2
) -> dict[str, dict]:
    """Build topics from high-frequency concepts (those appearing in 2+ sources)."""
    topics = {}
    for cslug, cdata in concepts.items():
        source_count = len(cdata["sources"])
        if source_count >= min_sources:
            topics[cslug] = {
                "title": cdata["title"],
                "sources": set(cdata["sources"]),
                "concepts": {cslug},
            }
    return topics


# ---------------------------------------------------------------------------
# Wiki file writing
# ---------------------------------------------------------------------------


def write_frontmatter_md(data: dict) -> str:
    """Convert a dict to YAML frontmatter string (minimal serializer)."""
    lines = ["---"]
    for key, value in data.items():
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
            elif all(isinstance(v, str) for v in value):
                # Check if it's a simple list that fits on one line
                # For wiki-links and other bracketed content, use multi-line
                has_brackets = any("[" in v or "{" in v for v in value)
                if len(value) <= 5 and not has_brackets:
                    items = ", ".join(value)
                    lines.append(f"{key}: [{items}]")
                else:
                    lines.append(f"{key}:")
                    for v in value:
                        lines.append(f'  - "{v}"')
            else:
                lines.append(f"{key}:")
                for v in value:
                    lines.append(f'  - "{v}"')
        elif isinstance(value, (int, float)):
            lines.append(f"{key}: {value}")
        elif isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif isinstance(value, str):
            # Escape quotes in string values
            escaped = value.replace('"', '\\"')
            lines.append(f'{key}: "{escaped}"')
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def write_source_md(
    doc: dict, entity_slugs: list[str], related_source_ids: list[str], dry_run: bool = False
) -> Optional[str]:
    """Generate the content for a wiki/sources/{source_id}.md file."""
    csl = doc["csl"]
    source_id = doc["source_id"]
    merkle_root = doc["merkle_root"]
    page_count = doc["page_count"]
    title = csl.get("title", "Untitled")
    resource_type = csl.get("source_type", csl.get("genre", "digital_pdf"))
    issued = csl.get("issued", {})
    if isinstance(issued, dict):
        date_parts = issued.get("date-parts", [[]])
    else:
        date_parts = [[]]

    # Tags
    tags = ["source/academic"]
    genre = csl.get("genre", "")
    if "neidan" in title.lower() or "internal alchem" in title.lower():
        tags.append("daoism/neidan")
    elif "taoism" in title.lower() or "daoism" in title.lower():
        tags.append("daoism/general")
    if "christian" in title.lower() or "holy cross" in title.lower():
        tags.append("christianity/mysticism")

    # Entity wiki-links
    entities = [wiki_link("entities", s) for s in entity_slugs]

    # Related sources
    related = [wiki_link("sources", sid) for sid in related_source_ids if sid != source_id]

    # Images
    image_names = [img.name for img in doc["images"]]

    # Citation
    citation = format_chicago_citation(csl)

    frontmatter = {
        "type": "source",
        "title": title,
        "citation": citation,
        "source_id": source_id,
        "merkle_root": merkle_root,
        "resource_type": resource_type,
        "pages": page_count,
        "tags": tags,
        "entities": entities,
        "related": related,
        "images": image_names,
        "updated": TODAY,
    }

    # Body
    body_trunc = doc["first_text"][:500] if doc["first_text"] else ""
    body_lines = [f"# {title}", ""]
    if citation:
        body_lines.append(f"> {citation}")
        body_lines.append("")
    if entity_slugs:
        author_names = ", ".join(entity_slugs)
        body_lines.append(f"**Author(s):** {', '.join(entities)}")
        body_lines.append("")
    if body_trunc:
        body_lines.append(body_trunc)
        body_lines.append("")
    body_lines.append("See full content in corpus.")

    content = write_frontmatter_md(frontmatter) + "\n\n" + "\n".join(body_lines) + "\n"
    return content


def write_entity_md(slug_val: str, display_name: str, source_ids: list[str]) -> str:
    """Generate the content for a wiki/entities/{slug}.md file."""
    sources = [wiki_link("sources", sid) for sid in source_ids]

    frontmatter = {
        "type": "entity",
        "title": display_name,
        "tags": ["entity/person"],
        "sources": sources,
        "updated": TODAY,
    }

    body_lines = [
        f"# {display_name}",
        "",
        "## Works",
        "",
    ]
    for wl in sources:
        body_lines.append(f"- {wl}")
    body_lines.append("")

    return write_frontmatter_md(frontmatter) + "\n\n" + "\n".join(body_lines) + "\n"


def write_concept_md(
    slug_val: str, title: str, aliases: list[str], source_ids: list[str], related: list[str]
) -> str:
    """Generate the content for a wiki/concepts/{slug}.md file."""
    sources = [wiki_link("sources", sid) for sid in sorted(source_ids)]
    related_links = [wiki_link("concepts", r) for r in sorted(related) if r != slug_val]

    # Auto-detect tags
    tags = ["concept"]
    title_lower = title.lower()
    if any(kw in title_lower for kw in ["neidan", "internal alchem", "waidan", "external alchem", "daoist", "taoist", "daoism", "taoism"]):
        tags.append("daoism/neidan")
    elif "healing" in title_lower or "daoyin" in title_lower or "導引" in title_lower:
        tags.append("daoism/practice")
    elif "christian" in title_lower or "prayer" in title_lower or "hesychasm" in title_lower:
        tags.append("christianity/mysticism")
    else:
        tags.append("general")

    frontmatter = {
        "type": "concept",
        "title": title,
        "aliases": aliases,
        "tags": tags,
        "sources": sources,
        "related": related_links,
        "updated": TODAY,
    }

    body_lines = [
        f"# {title}",
        "",
    ]
    if aliases:
        body_lines.append(f"**Aliases:** {', '.join(aliases)}")
        body_lines.append("")
    body_lines.append("## Sources")
    body_lines.append("")
    for wl in sources:
        body_lines.append(f"- {wl}")
    body_lines.append("")
    if related_links:
        body_lines.append("## Related Concepts")
        body_lines.append("")
        for rl in related_links:
            body_lines.append(f"- {rl}")
        body_lines.append("")

    return write_frontmatter_md(frontmatter) + "\n\n" + "\n".join(body_lines) + "\n"


def write_topic_md(
    slug_val: str, title: str, source_ids: list[str], concept_links: list[str]
) -> str:
    """Generate the content for a wiki/topics/{slug}.md file."""
    sources = [wiki_link("sources", sid) for sid in sorted(source_ids)]
    concepts = [wiki_link("concepts", c) for c in sorted(concept_links)]

    tags = ["topic"]
    title_lower = title.lower()
    if any(kw in title_lower for kw in ["alchemy", "neidan", "waidan", "elixir"]):
        tags.append("daoism/neidan")

    frontmatter = {
        "type": "topic",
        "title": title,
        "tags": tags,
        "sources": sources,
        "concepts": concepts,
        "updated": TODAY,
    }

    body_lines = [
        f"# {title}",
        "",
        "## Sources",
        "",
    ]
    for wl in sources:
        body_lines.append(f"- {wl}")
    body_lines.append("")
    if concepts:
        body_lines.append("## Concepts")
        body_lines.append("")
        for cl in concepts:
            body_lines.append(f"- {cl}")
        body_lines.append("")

    return write_frontmatter_md(frontmatter) + "\n\n" + "\n".join(body_lines) + "\n"


def write_index_md(
    title: str,
    category: str,
    entries: list[tuple[str, str]],
) -> str:
    """Generate an index file like wiki/sources/_index.md."""
    count = len(entries)
    frontmatter = {
        "type": "index",
        "title": title,
        "tags": ["index", category],
        "updated": TODAY,
    }

    body_lines = [
        f"# {title}",
        "",
    ]
    if entries:
        for slug_val, display_title in entries:
            body_lines.append(f"- {wiki_link(category, slug_val)} — {display_title}")
    else:
        body_lines.append("_(暂无 — 运行 export_vault.py 后自动填充)_")
    body_lines.append("")

    return write_frontmatter_md(frontmatter) + "\n\n" + "\n".join(body_lines) + "\n"


def write_root_index_md(
    source_count: int,
    entity_count: int,
    concept_count: int,
    topic_count: int,
    source_entries: list[tuple[str, str]],
    entity_entries: list[tuple[str, str]],
    concept_entries: list[tuple[str, str]],
    topic_entries: list[tuple[str, str]],
) -> str:
    """Generate wiki/_index.md."""
    frontmatter = {
        "type": "index",
        "title": "知识库索引",
        "aliases": ["Wiki Index", "Knowledge Base Index"],
        "tags": ["index", "meta"],
        "updated": TODAY,
    }

    body_lines = [
        "# 知识库索引",
        "",
        "> 此页面由 export_vault.py 自动维护。",
        "",
        "## 统计",
        "",
        f"- 来源页面: {source_count}",
        f"- 实体页面: {entity_count}",
        f"- 概念页面: {concept_count}",
        f"- 话题页面: {topic_count}",
        f"- 最后编译: {TODAY}",
        "",
        "## 来源",
        "",
    ]
    if source_entries:
        for s, t in source_entries:
            body_lines.append(f"- {wiki_link('sources', s)} — {t}")
    else:
        body_lines.append("_(暂无)_")
    body_lines.append("")

    body_lines.append("## 实体")
    body_lines.append("")
    if entity_entries:
        for s, t in entity_entries:
            body_lines.append(f"- {wiki_link('entities', s)} — {t}")
    else:
        body_lines.append("_(暂无)_")
    body_lines.append("")

    body_lines.append("## 概念")
    body_lines.append("")
    if concept_entries:
        for s, t in concept_entries:
            body_lines.append(f"- {wiki_link('concepts', s)} — {t}")
    else:
        body_lines.append("_(暂无)_")
    body_lines.append("")

    body_lines.append("## 话题")
    body_lines.append("")
    if topic_entries:
        for s, t in topic_entries:
            body_lines.append(f"- {wiki_link('topics', s)} — {t}")
    else:
        body_lines.append("_(暂无)_")
    body_lines.append("")

    return write_frontmatter_md(frontmatter) + "\n\n" + "\n".join(body_lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Export citeindex corpus JSON to nb-style wiki Markdown files",
    )
    parser.add_argument(
        "--corpus-root",
        default=str(Path(__file__).parent.parent / "corpus"),
        help="Path to corpus directory (default: ./corpus)",
    )
    parser.add_argument(
        "--wiki-root",
        default=str(Path(__file__).parent.parent / "library" / "wiki" / "aca-writer"),
        help="Path to wiki vault (default: ./wiki)",
    )
    parser.add_argument(
        "--llm",
        default="",
        help="Ollama model for topic/concept clustering (optional)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show progress output",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be written without writing",
    )
    args = parser.parse_args()

    corpus_root = Path(args.corpus_root).resolve()
    wiki_root = Path(args.wiki_root).resolve()

    if not corpus_root.is_dir():
        print(f"ERROR: Corpus root not found: {corpus_root}", file=sys.stderr)
        sys.exit(1)

    # ---------------------------------------------------------------
    # Step 1: Scan corpus
    # ---------------------------------------------------------------
    if args.verbose:
        print("Scanning corpus...")

    doc_dirs = scan_corpus(corpus_root)
    if not doc_dirs:
        print("No document directories found in corpus.", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        print(f"Found {len(doc_dirs)} document directories")

    all_doc_data: list[dict] = []
    for doc_dir in doc_dirs:
        data = load_doc_data(doc_dir)
        if data:
            all_doc_data.append(data)
        elif args.verbose:
            print(f"  Skipping {doc_dir.name} — no csl.json or load error")

    if args.verbose:
        for doc in all_doc_data:
            print(f"  {doc['source_id']}: {doc['csl'].get('title','?')} (merkle={doc['merkle_root'][:12]}...)")

    # ---------------------------------------------------------------
    # Step 2: Build entities (authors)
    # ---------------------------------------------------------------
    if args.verbose:
        print("Building entities...")

    entity_map: dict[str, dict] = {}  # slug -> {display_name, source_ids: list}
    for doc in all_doc_data:
        csl = doc["csl"]
        source_id = doc["source_id"]
        authors = csl.get("author", [])
        for author in authors:
            s = author_slug(author)
            dn = author_display_name(author)
            if s not in entity_map:
                entity_map[s] = {"display_name": dn, "source_ids": []}
            if source_id not in entity_map[s]["source_ids"]:
                entity_map[s]["source_ids"].append(source_id)

    # ---------------------------------------------------------------
    # Step 3: Extract concepts
    # ---------------------------------------------------------------
    if args.verbose:
        print("Extracting concepts...")

    concepts = extract_concepts_from_sections(all_doc_data)

    if args.verbose:
        print(f"  Found {len(concepts)} concepts")
        for cslug, cdata in sorted(concepts.items()):
            print(f"    {cslug}: {cdata['title']} ({len(cdata['sources'])} sources)")

    # ---------------------------------------------------------------
    # Step 4: Build topics
    # ---------------------------------------------------------------
    topics: dict[str, dict] = {}
    if args.llm:
        if args.verbose:
            print(f"Clustering topics with LLM ({args.llm})...")
        topics = llm_cluster_topics(all_doc_data, args.llm, args.verbose)
    else:
        if args.verbose:
            print("Building topics from high-frequency concepts...")
        topics = build_topics_from_frequency(concepts, min_sources=2)

    if args.verbose:
        print(f"  Found {len(topics)} topics")

    # Link topics to concepts
    for tslug, tdata in topics.items():
        # Find concepts that share sources with this topic
        for cslug, cdata in concepts.items():
            if tdata["sources"] & cdata["sources"]:
                tdata.setdefault("concepts", set()).add(cslug)

    # ---------------------------------------------------------------
    # Step 5: Build related sources
    # ---------------------------------------------------------------
    if args.verbose:
        print("Computing related sources...")

    # Sources sharing the same author are related
    author_to_sources: dict[str, list[str]] = defaultdict(list)
    for doc in all_doc_data:
        source_id = doc["source_id"]
        for author in doc["csl"].get("author", []):
            s = author_slug(author)
            author_to_sources[s].append(source_id)

    related_sources: dict[str, list[str]] = defaultdict(list)
    for author_s, sids in author_to_sources.items():
        for sid in sids:
            others = [s for s in sids if s != sid]
            related_sources[sid].extend(others)

    # ---------------------------------------------------------------
    # Step 6: Write wiki files
    # ---------------------------------------------------------------
    if args.verbose:
        print("Writing wiki files...")

    # Create directories
    for subdir in ["sources", "entities", "concepts", "topics"]:
        ensure_dir(wiki_root / subdir)

    written_files = 0
    skipped_files = 0

    # -- Sources --
    source_entries: list[tuple[str, str]] = []
    for doc in all_doc_data:
        source_id = doc["source_id"]
        title = doc["csl"].get("title", "Untitled")
        entity_slugs = []
        for author in doc["csl"].get("author", []):
            s = author_slug(author)
            if s not in entity_slugs:
                entity_slugs.append(s)
        rel_ids = list(set(related_sources.get(source_id, [])))
        content = write_source_md(doc, entity_slugs, rel_ids)

        filepath = wiki_root / "sources" / f"{source_id}.md"

        # Idempotency check
        if filepath.exists():
            existing_fm = read_frontmatter(filepath)
            if existing_fm and existing_fm.get("merkle_root") == doc["merkle_root"]:
                skipped_files += 1
                if args.verbose:
                    print(f"  [skip] sources/{source_id}.md (merkle unchanged)")
                source_entries.append((source_id, title))
                continue

        if not args.dry_run:
            filepath.write_text(content, encoding="utf-8")
            # Copy images
            if doc["images"]:
                img_dest_dir = wiki_root / "sources" / f"{source_id}_images"
                ensure_dir(img_dest_dir)
                for img_path in doc["images"]:
                    dest = img_dest_dir / img_path.name
                    if not dest.exists():
                        shutil.copy2(str(img_path), str(dest))
                        if args.verbose:
                            print(f"  [copy] {img_path.name} -> sources/{source_id}_images/")

        written_files += 1
        if args.verbose:
            print(f"  [write] sources/{source_id}.md")
        source_entries.append((source_id, title))

    # -- Entities --
    entity_entries: list[tuple[str, str]] = []
    for eslug, edata in sorted(entity_map.items()):
        content = write_entity_md(eslug, edata["display_name"], edata["source_ids"])
        filepath = wiki_root / "entities" / f"{eslug}.md"

        # Entities don't have merkle_root, so we always rewrite
        # (or we could check by content hash, but simplicity first)
        if not args.dry_run:
            filepath.write_text(content, encoding="utf-8")

        written_files += 1
        if args.verbose:
            print(f"  [write] entities/{eslug}.md")
        entity_entries.append((eslug, edata["display_name"]))

    # -- Concepts --
    concept_entries: list[tuple[str, str]] = []
    for cslug, cdata in sorted(concepts.items()):
        content = write_concept_md(
            cslug,
            cdata["title"],
            cdata["aliases"],
            sorted(cdata["sources"]),
            sorted(cdata["related"]),
        )
        filepath = wiki_root / "concepts" / f"{cslug}.md"

        if not args.dry_run:
            filepath.write_text(content, encoding="utf-8")

        written_files += 1
        if args.verbose:
            print(f"  [write] concepts/{cslug}.md")
        concept_entries.append((cslug, cdata["title"]))

    # -- Topics --
    topic_entries: list[tuple[str, str]] = []
    for tslug, tdata in sorted(topics.items()):
        content = write_topic_md(
            tslug,
            tdata["title"],
            sorted(tdata["sources"]),
            sorted(tdata.get("concepts", set())),
        )
        filepath = wiki_root / "topics" / f"{tslug}.md"

        if not args.dry_run:
            filepath.write_text(content, encoding="utf-8")

        written_files += 1
        if args.verbose:
            print(f"  [write] topics/{tslug}.md")
        topic_entries.append((tslug, tdata["title"]))

    # -- Index files --
    if not args.dry_run:
        # Sub-index files
        for category, title, entries in [
            ("sources", "来源索引", source_entries),
            ("entities", "实体索引", entity_entries),
            ("concepts", "概念索引", concept_entries),
            ("topics", "话题索引", topic_entries),
        ]:
            idx_path = wiki_root / category / "_index.md"
            idx_content = write_index_md(title, category, entries)
            idx_path.write_text(idx_content, encoding="utf-8")
            if args.verbose:
                print(f"  [write] {category}/_index.md ({len(entries)} entries)")

        # Root index
        root_idx = write_root_index_md(
            source_count=len(source_entries),
            entity_count=len(entity_entries),
            concept_count=len(concept_entries),
            topic_count=len(topic_entries),
            source_entries=source_entries,
            entity_entries=entity_entries,
            concept_entries=concept_entries,
            topic_entries=topic_entries,
        )
        (wiki_root / "_index.md").write_text(root_idx, encoding="utf-8")
        if args.verbose:
            print(f"  [write] _index.md")

    # ---------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------
    if args.dry_run:
        print("\n[DRY RUN] No files were written.")
    else:
        print(f"\nExport complete: wrote {written_files} files, skipped {skipped_files} (unchanged)")
        print(f"  Sources:   {len(source_entries)}")
        print(f"  Entities:  {len(entity_entries)}")
        print(f"  Concepts:  {len(concept_entries)}")
        print(f"  Topics:    {len(topic_entries)}")
        print(f"  Wiki root: {wiki_root}")


if __name__ == "__main__":
    main()
