"""Tests for Shutong MCP tools — error helpers, dispatch, glossary, corpus, registration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from shutong_backend.mcp_server import (
    TOOL_DEFINITIONS,
    _HANDLERS,
    call_tool,
)
from shutong_backend.tools.errors import ShutongError, error_response
from shutong_backend.tools import glossary, corpus


# ---------------------------------------------------------------------------
# 1. error_response helper
# ---------------------------------------------------------------------------


class TestErrorResponse:
    """Tests for shutong.tools.errors.error_response."""

    def test_returns_error_status(self):
        result = error_response("not_found", "Document missing")
        assert result["status"] == "error"
        assert result["error_code"] == "not_found"
        assert result["message"] == "Document missing"
        assert result["next_action"] == ""

    def test_with_next_action(self):
        result = error_response("invalid_input", "Bad arg", "Check parameters")
        assert result["next_action"] == "Check parameters"

    def test_all_keys_present(self):
        result = error_response("x", "y", "z")
        assert set(result.keys()) == {"status", "error_code", "message", "next_action"}


class TestShutongError:
    """Tests for shutong.tools.errors.ShutongError."""

    def test_is_exception(self):
        err = ShutongError("code", "msg")
        assert isinstance(err, Exception)

    def test_attributes(self):
        err = ShutongError("code", "msg", "retry")
        assert err.error_code == "code"
        assert err.message == "msg"
        assert err.next_action == "retry"

    def test_default_next_action(self):
        err = ShutongError("code", "msg")
        assert err.next_action == ""

    def test_str_is_message(self):
        err = ShutongError("code", "something broke")
        assert str(err) == "something broke"


# ---------------------------------------------------------------------------
# 2. call_tool dispatch
# ---------------------------------------------------------------------------


class TestCallTool:
    """Tests for the call_tool dispatch handler in mcp_server."""

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        result = await call_tool("shutong_nonexistent", {})
        assert len(result) == 1
        assert result[0]["type"] == "text"
        payload = json.loads(result[0]["text"])
        assert payload["status"] == "error"
        assert payload["error_code"] == "unknown_tool"

    @pytest.mark.asyncio
    async def test_unknown_tool_next_action(self):
        result = await call_tool("shutong_bogus", {})
        payload = json.loads(result[0]["text"])
        assert "list_tools" in payload["next_action"]

    @pytest.mark.asyncio
    async def test_result_is_text_json(self):
        """call_tool always wraps output as [{"type": "text", "text": json}]."""
        result = await call_tool("shutong_nonexistent", {})
        assert result[0]["type"] == "text"
        # Must be valid JSON
        parsed = json.loads(result[0]["text"])
        assert isinstance(parsed, dict)

    @pytest.mark.asyncio
    async def test_shutong_error_caught(self):
        """ShutongError raised inside a handler becomes an error_response."""
        fake_handler = AsyncMock(side_effect=ShutongError("bad_thing", "It broke", "Try again"))
        with patch.dict(_HANDLERS, {"shutong_test_err": fake_handler}):
            result = await call_tool("shutong_test_err", {})
        payload = json.loads(result[0]["text"])
        assert payload["status"] == "error"
        assert payload["error_code"] == "bad_thing"
        assert payload["message"] == "It broke"
        assert payload["next_action"] == "Try again"

    @pytest.mark.asyncio
    async def test_generic_exception_caught(self):
        """Generic exceptions are also caught and converted to error_response."""
        fake_handler = AsyncMock(side_effect=ValueError("unexpected problem"))
        with patch.dict(_HANDLERS, {"shutong_test_gen": fake_handler}):
            result = await call_tool("shutong_test_gen", {})
        payload = json.loads(result[0]["text"])
        assert payload["status"] == "error"
        assert payload["error_code"] == "ValueError"
        assert "unexpected problem" in payload["message"]

    @pytest.mark.asyncio
    async def test_none_arguments_treated_as_empty(self):
        """call_tool normalises None arguments to {}."""
        fake_handler = AsyncMock(return_value={"status": "ok"})
        with patch.dict(_HANDLERS, {"shutong_test_none": fake_handler}):
            result = await call_tool("shutong_test_none", None)
        fake_handler.assert_awaited_once_with({})
        payload = json.loads(result[0]["text"])
        assert payload["status"] == "ok"


# ---------------------------------------------------------------------------
# 3. Glossary tools (with tmp_path)
# ---------------------------------------------------------------------------


class TestGlossaryTools:
    """Integration tests for glossary tool handlers using a temporary glossary dir."""

    @pytest.mark.asyncio
    async def test_glossary_add_and_list(self, tmp_path):
        glossary_dir = str(tmp_path / "glossary")
        # Add an entry
        result = await glossary.glossary_add(
            {"term_en": "hypostasis", "term_zh": "位格"},
            glossary_dir,
        )
        assert result["status"] == "ok"
        assert result["term_en"] == "hypostasis"
        assert result["term_zh"] == "位格"

        # List should show it
        listed = await glossary.glossary_list({}, glossary_dir)
        assert listed["status"] == "ok"
        assert len(listed["files"]) >= 1
        # Find the default file
        entries_by_file = listed["files"]
        all_entries = {}
        for entries in entries_by_file.values():
            all_entries.update(entries)
        assert "hypostasis" in all_entries
        assert all_entries["hypostasis"] == "位格"

    @pytest.mark.asyncio
    async def test_glossary_add_to_custom_file(self, tmp_path):
        glossary_dir = str(tmp_path / "glossary")
        result = await glossary.glossary_add(
            {"term_en": "logos", "term_zh": "道", "file": "custom.json"},
            glossary_dir,
        )
        assert result["status"] == "ok"
        assert result["file"] == "custom.json"

        listed = await glossary.glossary_list({}, glossary_dir)
        assert "custom.json" in listed["files"]
        assert listed["files"]["custom.json"]["logos"] == "道"

    @pytest.mark.asyncio
    async def test_glossary_lookup_found(self, tmp_path):
        glossary_dir = str(tmp_path / "glossary")
        await glossary.glossary_add(
            {"term_en": "proskynesis", "term_zh": "敬拜"},
            glossary_dir,
        )
        result = await glossary.glossary_lookup(
            {"terms": ["proskynesis"]},
            glossary_dir,
        )
        assert result["status"] == "ok"
        assert "proskynesis" in result["results"]
        assert result["results"]["proskynesis"]["zh"] == "敬拜"

    @pytest.mark.asyncio
    async def test_glossary_lookup_missing_term(self, tmp_path):
        glossary_dir = str(tmp_path / "glossary")
        # empty glossary
        result = await glossary.glossary_lookup(
            {"terms": ["nonexistent"]},
            glossary_dir,
        )
        assert result["status"] == "ok"
        assert "nonexistent" not in result["results"]

    @pytest.mark.asyncio
    async def test_glossary_lookup_case_insensitive(self, tmp_path):
        glossary_dir = str(tmp_path / "glossary")
        await glossary.glossary_add(
            {"term_en": "Trinity", "term_zh": "三位一体"},
            glossary_dir,
        )
        result = await glossary.glossary_lookup(
            {"terms": ["trinity"]},
            glossary_dir,
        )
        assert result["status"] == "ok"
        assert "trinity" in result["results"]
        assert result["results"]["trinity"]["zh"] == "三位一体"

    @pytest.mark.asyncio
    async def test_glossary_load(self, tmp_path):
        glossary_dir = str(tmp_path / "glossary")
        # Create an external glossary file
        external = tmp_path / "external_gloss.json"
        external.write_text(
            json.dumps({"grace": "恩典", "faith": "信心"}, ensure_ascii=False),
            encoding="utf-8",
        )
        result = await glossary.glossary_load(
            {"filepath": str(external)},
            glossary_dir,
        )
        assert result["status"] == "ok"

        # Verify it was copied
        listed = await glossary.glossary_list({}, glossary_dir)
        assert "external_gloss.json" in listed["files"]
        assert listed["files"]["external_gloss.json"]["grace"] == "恩典"

    @pytest.mark.asyncio
    async def test_glossary_load_missing_file(self, tmp_path):
        glossary_dir = str(tmp_path / "glossary")
        with pytest.raises(FileNotFoundError):
            await glossary.glossary_load(
                {"filepath": "/nonexistent/path/file.json"},
                glossary_dir,
            )

    @pytest.mark.asyncio
    async def test_glossary_list_empty(self, tmp_path):
        glossary_dir = str(tmp_path / "glossary")
        result = await glossary.glossary_list({}, glossary_dir)
        assert result["status"] == "ok"
        assert result["files"] == {}

    @pytest.mark.asyncio
    async def test_glossary_add_multiple_entries(self, tmp_path):
        glossary_dir = str(tmp_path / "glossary")
        for en, zh in [("incarnation", "道成肉身"), ("resurrection", "复活")]:
            result = await glossary.glossary_add({"term_en": en, "term_zh": zh}, glossary_dir)
            assert result["status"] == "ok"

        listed = await glossary.glossary_list({}, glossary_dir)
        all_entries = {}
        for entries in listed["files"].values():
            all_entries.update(entries)
        assert all_entries["incarnation"] == "道成肉身"
        assert all_entries["resurrection"] == "复活"


# ---------------------------------------------------------------------------
# 4. Corpus tools (with tmp_path, mocked loader)
# ---------------------------------------------------------------------------


class TestCorpusTools:
    """Tests for corpus_status and corpus_tree using a mocked CorpusLoader."""

    @pytest.mark.asyncio
    async def test_corpus_status(self, tmp_path):
        """corpus_status with a mocked loader returning expected fields."""
        mock_loader = type(
            "FakeLoader",
            (),
            {
                "sources": [
                    {"source_id": "doc1", "csl": {"ingestion_timestamp": "2025-01-01"}},
                    {"source_id": "doc2"},
                ],
                "all_nodes": ["n1", "n2", "n3"],
                "csl_registry": [
                    {"ingestion_timestamp": "2025-01-01"},
                ],
                "merkle_registry": {"doc1": {"root": "abc123"}},
            },
        )()

        with patch("shutong_backend.tools.corpus._load_corpus_loader", return_value=mock_loader):
            result = await corpus.corpus_status({}, str(tmp_path))

        assert result["status"] == "ok"
        assert result["document_count"] == 2
        assert result["total_nodes"] == 3
        assert result["last_ingestion_time"] == "2025-01-01"
        assert result["merkle_health"]["documents_with_trees"] == 1
        assert result["merkle_health"]["documents_missing_trees"] == 1

    @pytest.mark.asyncio
    async def test_corpus_status_no_timestamps(self, tmp_path):
        """corpus_status when no ingestion timestamps exist."""
        mock_loader = type(
            "FakeLoader",
            (),
            {
                "sources": [],
                "all_nodes": [],
                "csl_registry": [],
                "merkle_registry": {},
            },
        )()

        with patch("shutong_backend.tools.corpus._load_corpus_loader", return_value=mock_loader):
            result = await corpus.corpus_status({}, str(tmp_path))

        assert result["status"] == "ok"
        assert result["document_count"] == 0
        assert result["total_nodes"] == 0
        assert result["last_ingestion_time"] is None

    @pytest.mark.asyncio
    async def test_corpus_tree(self, tmp_path):
        """corpus_tree returns document list with expected keys."""
        mock_loader = type(
            "FakeLoader",
            (),
            {
                "sources": [
                    {
                        "source_id": "Smith_2025_Logos",
                        "csl": {
                            "title": "On the Logos",
                            "author": [{"family": "Smith"}],
                            "issued": {"date-parts": [[2025]]},
                        },
                        "doc_dir": "/corpus/Smith_2025_Logos",
                    },
                ],
                "merkle_registry": {},
            },
        )()
        mock_loader.get_nodes_by_source = lambda sid: ["n1", "n2"]

        with patch("shutong_backend.tools.corpus._load_corpus_loader", return_value=mock_loader):
            result = await corpus.corpus_tree({}, str(tmp_path))

        assert result["status"] == "ok"
        assert len(result["documents"]) == 1
        doc = result["documents"][0]
        assert doc["source_id"] == "Smith_2025_Logos"
        assert doc["title"] == "On the Logos"
        assert doc["author"] == "Smith"
        assert doc["node_count"] == 2
        assert doc["document_path"] == "/corpus/Smith_2025_Logos"

    @pytest.mark.asyncio
    async def test_corpus_tree_empty(self, tmp_path):
        """corpus_tree with no documents."""
        mock_loader = type(
            "FakeLoader",
            (),
            {
                "sources": [],
                "merkle_registry": {},
            },
        )()

        with patch("shutong_backend.tools.corpus._load_corpus_loader", return_value=mock_loader):
            result = await corpus.corpus_tree({}, str(tmp_path))

        assert result["status"] == "ok"
        assert result["documents"] == []


# ---------------------------------------------------------------------------
# 5. Public MCP handlers
# ---------------------------------------------------------------------------


EXPECTED_TOOL_NAMES = [
    "shutong_search",
    "shutong_status",
    "shutong_state_wake_up",
    "shutong_state_snapshot",
    "shutong_state_record_session",
    "shutong_bibliography_search",
    "shutong_bibliography_source_catalog",
    "shutong_ingest",
    "shutong_ingest_status",
    "shutong_delete_document",
    "shutong_verify",
    "shutong_paper_audit",
    "shutong_paper_export_docx",
    "shutong_paper_status",
    "shutong_paper_use",
    "shutong_workspace",
    "shutong_bibliography",
    "shutong_source",
    "shutong_corpus",
    "shutong_citation",
    "shutong_memory",
    "shutong_outreach",
    "shutong_verifier_report",
]


class TestHandlerRegistration:
    """Only the 24-tool public contract is registered in _HANDLERS."""

    def test_handler_count(self):
        assert len(_HANDLERS) == 24, f"Expected public handler surface, got {len(_HANDLERS)}"

    @pytest.mark.parametrize("name", EXPECTED_TOOL_NAMES)
    def test_handler_registered(self, name):
        assert name in _HANDLERS, f"Handler for {name!r} not in _HANDLERS"

# ---------------------------------------------------------------------------
# 6. Public MCP tool definitions
# ---------------------------------------------------------------------------


class TestToolDefinitions:
    """Only the conductor-facing public surface is advertised."""

    def test_definition_count(self):
        assert len(TOOL_DEFINITIONS) == 24, (
            f"Expected current tool surface, got {len(TOOL_DEFINITIONS)}"
        )

    def test_paper_tools_are_registered(self):
        names = {tool["name"] for tool in TOOL_DEFINITIONS}
        assert {"shutong_paper_use", "shutong_paper_status", "shutong_paper_audit", "shutong_bibliography", "shutong_source"} <= names

    def test_workspace_planner_tools_are_registered(self):
        names = {tool["name"] for tool in TOOL_DEFINITIONS}
        assert "shutong_workspace" in names

    def test_all_definitions_have_required_keys(self):
        for defn in TOOL_DEFINITIONS:
            assert "name" in defn, f"Missing 'name' in definition: {defn}"
            assert "description" in defn, f"Missing 'description' in {defn['name']}"
            assert "inputSchema" in defn, f"Missing 'inputSchema' in {defn['name']}"

    def test_no_duplicate_names(self):
        names = [d["name"] for d in TOOL_DEFINITIONS]
        assert len(names) == len(set(names)), f"Duplicate tool names found: {names}"

    def test_handlers_and_definitions_match(self):
        """Every handler must have a matching definition and vice versa."""
        handler_names = set(_HANDLERS.keys())
        definition_names = {d["name"] for d in TOOL_DEFINITIONS}
        assert definition_names == handler_names

    def test_group_actions_have_action_specific_required_fields(self):
        workspace = next(tool for tool in TOOL_DEFINITIONS if tool["name"] == "shutong_workspace")
        create_paper = next(branch for branch in workspace["inputSchema"]["oneOf"] if branch["properties"]["action"]["const"] == "create_paper")
        assert create_paper["required"] == ["action", "paper_id", "title"]

    def test_passage_search_accepts_query_or_seed(self):
        search = next(tool for tool in TOOL_DEFINITIONS if tool["name"] == "shutong_search")
        branch = next(item for item in search["inputSchema"]["oneOf"]
                      if item["properties"]["mode"]["enum"] == ["passages"])
        assert branch["anyOf"] == [{"required": ["query"]}, {"required": ["seed"]}]


class TestPublicDispatch:
    @pytest.mark.asyncio
    async def test_removed_tool_is_unknown(self):
        result = await call_tool("shutong_translate", {})
        assert json.loads(result[0]["text"])["error_code"] == "unknown_tool"

    @pytest.mark.asyncio
    async def test_group_action_rejects_missing_fields(self):
        result = await call_tool("shutong_workspace", {"action": "create_paper", "paper_id": "test"})
        payload = json.loads(result[0]["text"])
        assert payload["error_code"] == "invalid_input"
