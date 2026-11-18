"""Regression tests for the 2026-11-18 code review findings.

Covers: mutually exclusive ``shutong_verify`` / ``shutong_search`` schemas,
fail-closed integrity verification, ambiguous citation resolution, bounded
regex search, MCP stdout framing, and passport ID traversal.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import re
import sys
import threading

import pytest
from jsonschema import Draft202012Validator

from shutong_backend import mcp_server
from shutong_backend.mcp_server import TOOL_DEFINITIONS
from shutong_backend.passport import InvalidPassportId, MaterialPassport
from shutong_backend.tools import research, verify
from shutong_backend.tools.errors import ShutongError

PASSPORT_ID_RE = re.compile(r"pp-[0-9a-f]{8}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool(name: str) -> dict:
    return next(tool for tool in TOOL_DEFINITIONS if tool["name"] == name)


def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(_tool(name)["inputSchema"])


def _assert_valid(name: str, payload: dict) -> None:
    errors = list(_validator(name).iter_errors(payload))
    assert not errors, f"{payload!r} should validate for {name}: {[e.message for e in errors]}"


def _assert_invalid(name: str, payload: dict) -> None:
    assert list(_validator(name).iter_errors(payload)), f"{payload!r} should NOT validate for {name}"


class _FakeLoader:
    """Minimal CorpusLoader stand-in for integrity and citation tests."""

    def __init__(self, sources, nodes_by_source=None, merkle=None):
        self.sources = sources
        self._nodes_by_source = nodes_by_source or {}
        self.merkle_registry = merkle or {}

    def get_nodes_by_source(self, source_id):
        return self._nodes_by_source.get(source_id, [])


def _source(source_id="docA", family="Smith", year=2020, title="A Title"):
    return {
        "source_id": source_id,
        "doc_dir": f"/corpus/{source_id}",
        "csl": {
            "id": source_id,
            "title": title,
            "author": [{"family": family}],
            "issued": {"date-parts": [[year]]},
        },
    }


def _merkle_for(nodes):
    from citeindex.ingestion.deterministic import build_merkle_tree

    return build_merkle_tree([node["sha256"] for node in nodes])


def _node(text, source_id="docA", node_id="docA:1"):
    from citeindex.ingestion.deterministic import hash_payload

    return {
        "source_id": source_id,
        "node_id": node_id,
        "text": text,
        "sha256": hash_payload(text),
    }


def _fake_loader_class(nodes):
    class _Loader:
        sources: list = []

        def __init__(self, corpus_root):
            self.corpus_root = corpus_root

        def load(self):
            return None

        @property
        def all_nodes(self):
            return nodes

    return _Loader


# ---------------------------------------------------------------------------
# 1. Tool schemas validate and are mutually exclusive
# ---------------------------------------------------------------------------


class TestToolSchemas:
    def test_every_tool_schema_is_a_valid_json_schema(self):
        for tool in TOOL_DEFINITIONS:
            Draft202012Validator.check_schema(tool["inputSchema"])

    @pytest.mark.parametrize(
        "payload",
        [
            {"csl_id": "docA"},
            {"mode": "node", "csl_id": "docA"},
            {"mode": "all"},
            {"mode": "all", "node_hash": None},
        ],
    )
    def test_verify_accepts_documented_shapes(self, payload):
        _assert_valid("shutong_verify", payload)

    def test_advertised_verify_schema_accepts_default_mode(self):
        """The schema a client actually receives must accept the default shape."""
        from shutong_backend.mcp_server import list_tools

        tools = asyncio.run(list_tools())
        schema = next(tool for tool in tools if tool.name == "shutong_verify").inputSchema
        validator = Draft202012Validator(schema)
        assert not list(validator.iter_errors({"csl_id": "docA"}))
        assert not list(validator.iter_errors({"mode": "node", "csl_id": "docA"}))
        assert not list(validator.iter_errors({"mode": "all"}))
        assert list(validator.iter_errors({"mode": "node"}))

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"mode": "node"},
            {"mode": "all", "csl_id": "docA"},
            {"mode": "bogus", "csl_id": "docA"},
            {"node_hash": "abc"},
        ],
    )
    def test_verify_rejects_malformed_shapes(self, payload):
        _assert_invalid("shutong_verify", payload)

    @pytest.mark.parametrize(
        "payload",
        [
            {"query": "nicene"},
            {"mode": "keyword", "query": "nicene"},
            {"pattern": "nicene"},
            {"mode": "regex", "pattern": "nicene"},
        ],
    )
    def test_search_accepts_documented_shapes(self, payload):
        _assert_valid("shutong_search", payload)

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"mode": "regex"},
            {"mode": "regex", "query": "nicene"},
            {"mode": "keyword", "pattern": "nicene"},
            {"query": "nicene", "pattern": "nicene"},
        ],
    )
    def test_search_rejects_malformed_shapes(self, payload):
        _assert_invalid("shutong_search", payload)


# ---------------------------------------------------------------------------
# 2. Integrity verification fails closed
# ---------------------------------------------------------------------------


class TestIntegrityFailsClosed:
    def test_document_without_nodes_fails(self):
        loader = _FakeLoader([_source()])
        result = verify._verify_document(loader, loader.sources[0])
        assert result["status"] == "fail"
        reasons = {mismatch["reason"] for mismatch in result["mismatches"]}
        assert "no_nodes" in reasons
        assert "missing_merkle_evidence" in reasons
        assert result["reason"] == "no_nodes"

    def test_document_without_merkle_evidence_fails(self):
        nodes = [_node("Alpha")]
        loader = _FakeLoader([_source()], {"docA": nodes})
        result = verify._verify_document(loader, loader.sources[0])
        assert result["status"] == "fail"
        assert result["reason"] == "missing_merkle_evidence"

    def test_document_without_text_content_fails(self):
        nodes = [_node("")]
        loader = _FakeLoader(
            [_source()],
            {"docA": nodes},
            {"docA": _merkle_for(nodes)},
        )
        result = verify._verify_document(loader, loader.sources[0])
        assert result["status"] == "fail"
        assert result["reason"] == "missing_document_content"

    def test_complete_document_still_passes(self):
        nodes = [_node("Alpha"), _node("Beta", node_id="docA:2")]
        loader = _FakeLoader(
            [_source()],
            {"docA": nodes},
            {"docA": _merkle_for(nodes)},
        )
        result = verify._verify_document(loader, loader.sources[0])
        assert result["status"] == "pass", result
        assert result["nodes_checked"] == 2
        assert result["mismatches"] == []

    @pytest.mark.asyncio
    async def test_empty_corpus_fails_verify_all(self, monkeypatch, tmp_path):
        loader = _FakeLoader([])
        monkeypatch.setattr(verify, "_load_corpus_loader", lambda root: loader)
        result = await verify.verify_all({}, str(tmp_path))
        assert result["status"] == "fail"
        assert result["reason"] == "no_documents"
        assert result["documents"] == []


# ---------------------------------------------------------------------------
# 3. Citation resolution refuses to pick among duplicates
# ---------------------------------------------------------------------------


class TestResolveCitation:
    @pytest.mark.asyncio
    async def test_unique_match_resolves(self, monkeypatch, tmp_path):
        loader = _FakeLoader([_source("docA")])
        monkeypatch.setattr(verify, "_load_corpus_loader", lambda root: loader)
        result = await verify.resolve_citation({"citation_key": "Smith 2020"}, str(tmp_path))
        assert result["status"] == "ok"
        assert result["source_id"] == "docA"

    @pytest.mark.asyncio
    async def test_duplicate_author_year_is_ambiguous(self, monkeypatch, tmp_path):
        loader = _FakeLoader([_source("docA"), _source("docB")])
        monkeypatch.setattr(verify, "_load_corpus_loader", lambda root: loader)
        result = await verify.resolve_citation({"citation_key": "Smith 2020"}, str(tmp_path))
        assert result["status"] == "ambiguous"
        assert result["error_code"] == "ambiguous_citation"
        assert {candidate["source_id"] for candidate in result["candidates"]} == {"docA", "docB"}

    @pytest.mark.asyncio
    async def test_exact_source_id_disambiguates(self, monkeypatch, tmp_path):
        loader = _FakeLoader([_source("docA"), _source("docB")])
        monkeypatch.setattr(verify, "_load_corpus_loader", lambda root: loader)
        result = await verify.resolve_citation({"citation_key": "docB"}, str(tmp_path))
        assert result["status"] == "ok"
        assert result["source_id"] == "docB"

    @pytest.mark.asyncio
    async def test_unknown_citation_is_not_found(self, monkeypatch, tmp_path):
        loader = _FakeLoader([_source("docA")])
        monkeypatch.setattr(verify, "_load_corpus_loader", lambda root: loader)
        result = await verify.resolve_citation({"citation_key": "Nobody 1999"}, str(tmp_path))
        assert result["status"] == "error"
        assert result["error_code"] == "not_found"


# ---------------------------------------------------------------------------
# 4. Regex search is bounded and leaves the event loop
# ---------------------------------------------------------------------------


class TestBoundedRegexSearch:
    def test_nested_quantifier_is_rejected(self):
        with pytest.raises(ShutongError) as excinfo:
            research.compile_bounded_pattern("(a+)+b")
        assert excinfo.value.error_code == "unsafe_pattern"

    def test_ambiguous_quantified_alternation_is_rejected(self):
        with pytest.raises(ShutongError) as excinfo:
            research.compile_bounded_pattern("(a|aa)+")
        assert excinfo.value.error_code == "unsafe_pattern"

    @pytest.mark.parametrize("pattern", [r"(a+)\1", r"(?P<x>a+)(?P=x)+"])
    def test_backreferences_are_rejected(self, pattern):
        with pytest.raises(ShutongError) as excinfo:
            research.compile_bounded_pattern(pattern)
        assert excinfo.value.error_code == "unsafe_pattern"

    def test_long_adversarial_pattern_is_rejected_before_compilation(self):
        pattern = "(a+)+" * 200
        assert len(pattern) > research.MAX_PATTERN_LENGTH
        with pytest.raises(ShutongError) as excinfo:
            research.compile_bounded_pattern(pattern)
        assert excinfo.value.error_code == "pattern_too_long"

    def test_safe_patterns_still_compile(self):
        for pattern in ("nicene", r"^[A-Z][a-z]+$", r"\d{2,4}-\d{2}", r"(a+)?"):
            assert research.compile_bounded_pattern(pattern) is not None

    @pytest.mark.asyncio
    async def test_dot_pattern_caps_match_count(self, monkeypatch, tmp_path):
        nodes = [
            {"source_id": "docA", "node_id": f"docA:{index}", "text": "a" * 600}
            for index in range(250)
        ]
        monkeypatch.setattr(
            "shutong_backend.agents.corpus_loader.CorpusLoader",
            _fake_loader_class(nodes),
        )
        result = await research.regex_search({"pattern": "."}, str(tmp_path))
        assert result["status"] == "ok"
        assert result["truncated"] is True
        assert result["match_count"] == research.MAX_MATCHES
        assert len(result["matches"]) == research.MAX_MATCHES
        assert all(len(match["text"]) <= research.MAX_MATCH_TEXT_CHARS for match in result["matches"])

    @pytest.mark.asyncio
    async def test_dot_pattern_caps_total_bytes(self, monkeypatch, tmp_path):
        nodes = [
            {"source_id": "docA", "node_id": f"docA:{index}", "text": "漢" * 500}
            for index in range(60)
        ]
        monkeypatch.setattr(
            "shutong_backend.agents.corpus_loader.CorpusLoader",
            _fake_loader_class(nodes),
        )
        result = await research.regex_search({"pattern": "."}, str(tmp_path))
        total_bytes = sum(len(match["text"].encode("utf-8")) for match in result["matches"])
        assert result["truncated"] is True
        assert result["match_count"] < research.MAX_MATCHES
        assert total_bytes <= research.MAX_TOTAL_BYTES + research.MAX_MATCH_TEXT_CHARS * 4

    @pytest.mark.asyncio
    async def test_pattern_limit_is_enforced_through_the_tool(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "shutong_backend.agents.corpus_loader.CorpusLoader",
            _fake_loader_class([]),
        )
        with pytest.raises(ShutongError) as excinfo:
            await research.regex_search({"pattern": "a" * (research.MAX_PATTERN_LENGTH + 1)}, str(tmp_path))
        assert excinfo.value.error_code == "pattern_too_long"

    def test_regex_matching_runs_off_the_event_loop(self, monkeypatch):
        seen = {}

        def fake_sync(args, corpus_root):
            seen["thread"] = threading.current_thread()
            return {"status": "ok", "matches": []}

        monkeypatch.setattr(research, "_regex_search_sync", fake_sync)
        asyncio.run(research.regex_search({"pattern": "nicene"}, "corpus"))
        assert seen["thread"] is not threading.main_thread()


# ---------------------------------------------------------------------------
# 5. Incidental stdout from third-party handlers cannot corrupt MCP frames
# ---------------------------------------------------------------------------


class TestStdoutGuard:
    def test_incidental_prints_go_to_stderr(self, capsys):
        with mcp_server.stdout_guard():
            print("citeindex: page 1/3")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "citeindex: page 1/3" in captured.err

    def test_stream_captured_before_redirection_stays_clean(self, capsys):
        # stdio_server wraps the process stdout before the server loop starts.
        protocol = io.StringIO()
        with mcp_server.stdout_guard():
            print("third-party progress output")
            protocol.write('{"jsonrpc":"2.0","id":1,"result":{}}\n')
        captured = capsys.readouterr()
        assert captured.out == ""
        assert protocol.getvalue() == '{"jsonrpc":"2.0","id":1,"result":{}}\n'

    @pytest.mark.asyncio
    async def test_worker_thread_prints_are_redirected(self, capsys):
        async def noisy_handler():
            return await asyncio.to_thread(lambda: print("ingest worker log"))

        with mcp_server.stdout_guard():
            await noisy_handler()
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "ingest worker log" in captured.err

    @pytest.mark.asyncio
    async def test_main_redirects_only_inside_the_transport(self, monkeypatch, capsys):
        protocol = io.StringIO()
        seen: dict[str, object] = {}

        @contextlib.asynccontextmanager
        async def fake_stdio_server():
            seen["stdout_at_transport"] = sys.stdout
            yield ("read", "write")

        async def fake_run(read_stream, write_stream, options):
            seen["stdout_during_run"] = sys.stdout
            seen["stderr_during_run"] = sys.stderr
            protocol.write('{"jsonrpc":"2.0","id":1}\n')
            print("citeindex noise")

        monkeypatch.setattr(mcp_server, "stdio_server", fake_stdio_server)
        monkeypatch.setattr(mcp_server.server, "run", fake_run)
        before = sys.stdout
        await mcp_server.main()
        captured = capsys.readouterr()
        assert seen["stdout_during_run"] is not seen["stdout_at_transport"]
        assert seen["stdout_during_run"] is seen["stderr_during_run"]
        assert sys.stdout is before
        assert captured.out == ""
        assert "citeindex noise" in captured.err
        assert protocol.getvalue() == '{"jsonrpc":"2.0","id":1}\n'


# ---------------------------------------------------------------------------
# 6. Passport IDs cannot escape the passport directory
# ---------------------------------------------------------------------------


class TestPassportIdValidation:
    @pytest.mark.parametrize(
        "bad_id",
        [
            "../outside",
            "../../../../etc/passwd",
            "pp-../../outside",
            "/etc/passwd",
            "pp-1234567",
            "pp-123456789",
            "pp-ABCDEF12",
            "pp-1234567g",
            "pp-12345678/../x",
            None,
            12345678,
        ],
    )
    def test_invalid_ids_are_rejected_before_io(self, tmp_path, bad_id):
        store = MaterialPassport(passport_dir=str(tmp_path / "passport"))
        for operation in (
            store.load,
            store.summary,
            lambda value: store.update(value, {}),
            lambda value: store._save({"passport_id": value}),
        ):
            with pytest.raises(InvalidPassportId):
                operation(bad_id)

    def test_path_traversal_cannot_read_outside_passport_dir(self, tmp_path):
        passport_dir = tmp_path / "passport"
        passport_dir.mkdir()
        outside = tmp_path / "outside.json"
        outside.write_text(json.dumps({"project_name": "Secret"}), encoding="utf-8")
        store = MaterialPassport(passport_dir=str(passport_dir))
        with pytest.raises(InvalidPassportId):
            store.load(os.path.join("..", "outside"))

    def test_created_ids_match_the_published_pattern(self, tmp_path):
        store = MaterialPassport(passport_dir=str(tmp_path / "passport"))
        created = store.create("Nicaea")
        assert PASSPORT_ID_RE.fullmatch(created["passport_id"])
        assert store.load(created["passport_id"])["project_name"] == "Nicaea"
