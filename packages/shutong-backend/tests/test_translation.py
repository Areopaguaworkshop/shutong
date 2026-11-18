"""Tests for the Shutong translation pipeline (Phase 2)."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from shutong_backend.translation.pipeline import (
    resolve_source,
    segment_document,
    build_system_prompt,
    flag_untranslated,
    render_interleaved,
)
from shutong_backend.translation.glossary import load_all_glossaries


# ---------------------------------------------------------------------------
# Task 11: resolve_source
# ---------------------------------------------------------------------------


class TestResolveSource:
    def test_resolve_source_csl_id(self, tmp_path):
        """Resolve a csl_id to a corpus document."""
        corpus = tmp_path / "corpus" / "Smith_2025_Logos"
        corpus.mkdir(parents=True)
        (corpus / "document.json").write_text(
            json.dumps({"title": "Test", "id": "Smith_2025_Logos"}), encoding="utf-8"
        )

        result = resolve_source("Smith_2025_Logos", corpus_root=str(tmp_path / "corpus"))
        assert result["source_type"] == "corpus"
        assert result["source_id"] == "Smith_2025_Logos"
        assert "title" in result

    def test_resolve_source_file_path(self, tmp_path):
        """Resolve a file path to a source document."""
        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"%PDF-1.4 test")

        result = resolve_source(str(pdf), corpus_root=str(tmp_path / "corpus"))
        assert result["source_type"] == "file"
        assert "file_path" in result or "source_id" in result

    def test_resolve_source_plain_text(self):
        """Plain text string is passed through."""
        result = resolve_source("The quick brown fox", corpus_root="./corpus")
        assert result["source_type"] == "text"
        assert "units" in result


# ---------------------------------------------------------------------------
# Task 12: segment_document
# ---------------------------------------------------------------------------


class TestSegmentDocument:
    def test_segment_document_headings_and_paragraphs(self, tmp_path):
        """Split document into translation units at paragraph level."""
        doc_dir = tmp_path / "Test_2025_Doc"
        doc_dir.mkdir(parents=True)
        (doc_dir / "document.json").write_text(
            json.dumps({"title": "Test Document", "id": "Test_2025_Doc"}),
            encoding="utf-8",
        )
        (doc_dir / "pageindex_tree.json").write_text(
            json.dumps({
                "children": [
                    {
                        "text": "Introduction",
                        "type": "heading",
                        "children": [
                            {
                                "text": "This is the first paragraph with a citation (Smith 2025, 42).",
                                "type": "paragraph",
                            },
                            {
                                "text": "Second paragraph about hypostasis and logos.",
                                "type": "paragraph",
                            },
                        ],
                    }
                ]
            }),
            encoding="utf-8",
        )

        doc = {
            "source_id": "Test_2025_Doc",
            "source_type": "corpus",
            "document_path": str(doc_dir),
        }
        units = segment_document(doc)
        assert len(units) >= 3  # heading + 2 paragraphs
        assert units[0]["type"] == "heading"
        assert units[1]["type"] == "paragraph"

    def test_segment_document_fallback_no_pageindex(self, tmp_path):
        """Fallback when pageindex_tree.json doesn't exist."""
        doc = {
            "source_id": "inline-text",
            "source_type": "text",
            "units": [{"text": "Paragraph one.\n\nParagraph two.", "citation": None}],
        }
        units = segment_document(doc)
        assert len(units) >= 1


# ---------------------------------------------------------------------------
# Task 13: build_system_prompt
# ---------------------------------------------------------------------------


class TestBuildSystemPrompt:
    def test_build_system_prompt_includes_glossary(self):
        """Glossary terms must be injected into the system prompt."""
        glossary = {"hypostasis": "位格", "logos": "道", "Peshitta": "贝西大"}
        prompt = build_system_prompt(glossary)

        assert "位格" in prompt
        assert "道" in prompt
        assert "贝西大" in prompt
        assert "Mandatory" in prompt or "mandatory" in prompt
        assert "DO NOT override" in prompt or "do not override" in prompt

    def test_build_system_prompt_empty_glossary(self):
        """System prompt works with empty glossary."""
        prompt = build_system_prompt({})
        assert "scholarly" in prompt.lower() or "translator" in prompt.lower()

    def test_build_system_prompt_untranslated_marker(self):
        """System prompt includes the [未译: ...] instruction for missing terms."""
        prompt = build_system_prompt({})
        assert "未译" in prompt


# ---------------------------------------------------------------------------
# Task 14: flag_untranslated
# ---------------------------------------------------------------------------


class TestFlagUntranslated:
    def test_flag_untranslated_marks_missing_terms(self):
        """Proper nouns without glossary entries get [未译: ...] markers."""
        zh_text = "这是关于Ephrem的讨论。"
        en_text = "This is about Ephrem's discussion."
        glossary = {"hypostasis": "位格", "logos": "道"}  # no Ephrem entry

        result = flag_untranslated(zh_text, en_text, glossary)
        assert "[未译: Ephrem]" in result

    def test_flag_untranslated_preserves_glossary_terms(self):
        """Glossary terms are NOT flagged as untranslated."""
        zh_text = "位格是道的体现。"
        en_text = "The hypostasis is the manifestation of the logos."
        glossary = {"hypostasis": "位格", "logos": "道"}

        result = flag_untranslated(zh_text, en_text, glossary)
        assert "[未译:" not in result


# ---------------------------------------------------------------------------
# Task 15: render_interleaved
# ---------------------------------------------------------------------------


class TestRenderInterleaved:
    def test_render_interleaved_produces_valid_md(self, tmp_path):
        """Interleaved bilingual Markdown has frontmatter and alternating EN/ZH blocks."""
        doc = {"source_id": "Test_2025_Doc", "source_type": "corpus", "title": "Test Document"}
        units = [
            {"type": "heading", "text": "Introduction", "citation": None},
            {
                "type": "paragraph",
                "text": "The hypostasis of the logos.",
                "citation": "(Smith 2025, 42)",
            },
        ]
        translated = ["引言", "道的位格。"]

        output = render_interleaved(doc, units, translated, str(tmp_path))

        content = output.read_text(encoding="utf-8")
        assert "---" in content  # frontmatter
        assert "source: Test_2025_Doc" in content
        assert "Introduction" in content
        assert "引言" in content
        assert "道的位格" in content