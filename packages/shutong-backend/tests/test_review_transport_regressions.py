"""Regression tests for reviewed transport guards and ingestion delete consistency.

These exercise pure request helpers, the SSE limiter and the delete registry
path directly; no listening sockets or user services are involved.
"""

from __future__ import annotations

import json

import pytest

from shutong_backend import server
from shutong_backend import papers
from shutong_backend.tools import ingest

TOKEN = "s3cr3t-token-for-tests-0123456789"


# ---------------------------------------------------------------------------
# Bearer-token authorization
# ---------------------------------------------------------------------------


def test_authorize_accepts_only_the_configured_bearer_token():
    assert server._authorize_request([], TOKEN).status == 401
    assert server._authorize_request(["Basic abc"], TOKEN).status == 401
    assert server._authorize_request(["Bearer"], TOKEN).status == 401
    assert server._authorize_request(["Bearer wrong-token-value"], TOKEN).code == "unauthorized"
    assert server._authorize_request([f"Bearer {TOKEN}"], TOKEN) is None
    # The auth scheme is case-insensitive per RFC 9110.
    assert server._authorize_request([f"bearer {TOKEN}"], TOKEN) is None


def test_authorize_fails_closed_without_a_configured_token():
    error = server._authorize_request([f"Bearer {TOKEN}"], None)
    assert error is not None and error.status == 401


def test_authorize_rejects_duplicate_authorization_headers():
    error = server._authorize_request([f"Bearer {TOKEN}", f"Bearer {TOKEN}"], TOKEN)
    assert error is not None and error.status == 401


def test_required_token_refuses_missing_or_short_configuration(monkeypatch):
    monkeypatch.delenv("SHUTONG_HTTP_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        server._required_token()

    monkeypatch.setenv("SHUTONG_HTTP_TOKEN", "   ")
    with pytest.raises(SystemExit):
        server._required_token()

    monkeypatch.setenv("SHUTONG_HTTP_TOKEN", "short")
    with pytest.raises(SystemExit):
        server._required_token()

    monkeypatch.setenv("SHUTONG_HTTP_TOKEN", TOKEN)
    assert server._required_token() == TOKEN


def test_main_refuses_to_start_without_a_token(monkeypatch):
    monkeypatch.delenv("SHUTONG_HTTP_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        server.main(["--port", "0"])


# ---------------------------------------------------------------------------
# Origin / Host validation
# ---------------------------------------------------------------------------


def test_same_origin_loopback_browser_request_is_allowed():
    assert server._validate_local_request("http://127.0.0.1:8765", "127.0.0.1:8765", 8765) is None
    assert server._validate_local_request("http://localhost:8765", "localhost:8765", 8765) is None
    assert server._validate_local_request("http://[::1]:8765", "[::1]:8765", 8765) is None


def test_tui_native_fetch_without_origin_is_allowed():
    assert server._validate_local_request(None, "127.0.0.1:8765", 8765) is None
    assert server._validate_local_request(None, "localhost:8765", 8765) is None


def test_request_without_origin_still_requires_a_loopback_host():
    for host in (None, "", "user@127.0.0.1:8765", "evil.example:8765"):
        error = server._validate_local_request(None, host, 8765)
        assert error is not None and error.status == 403 and error.code == "origin_refused", host


def test_hostile_origin_is_refused():
    error = server._validate_local_request("https://evil.example", "127.0.0.1:8765", 8765)
    assert error is not None and error.status == 403 and error.code == "origin_refused"


def test_opaque_origin_is_refused():
    error = server._validate_local_request("null", "127.0.0.1:8765", 8765)
    assert error is not None and error.status == 403


def test_loopback_origin_on_another_port_is_refused():
    error = server._validate_local_request("http://127.0.0.1:9999", "127.0.0.1:8765", 8765)
    assert error is not None and error.status == 403


def test_origin_must_match_the_host_header():
    error = server._validate_local_request("http://127.0.0.1:8765", "evil.example:8765", 8765)
    assert error is not None and error.status == 403
    assert server._validate_local_request("http://127.0.0.1:8765", None, 8765).status == 403


def test_dns_rebinding_host_is_refused_even_without_origin():
    error = server._validate_local_request(None, "evil.example:8765", 8765)
    assert error is not None and error.status == 403
    assert server._validate_local_request(None, "127.0.0.1:9999", 8765).status == 403


def test_cross_site_fetch_metadata_is_refused():
    error = server._validate_local_request(None, "127.0.0.1:8765", 8765, fetch_site="cross-site")
    assert error is not None and error.status == 403
    assert server._validate_local_request("http://127.0.0.1:8765", "127.0.0.1:8765", 8765, fetch_site="same-origin") is None


# ---------------------------------------------------------------------------
# Request framing and JSON body decoding
# ---------------------------------------------------------------------------


def test_content_length_parsing_accepts_bounded_values():
    assert server._parse_content_length([], None) == 0
    assert server._parse_content_length(["0"], None) == 0
    assert server._parse_content_length(["42"], None) == 42
    assert server._parse_content_length([str(server.MAX_BODY_BYTES)], None) == server.MAX_BODY_BYTES
    assert server._parse_content_length(["10"], "identity") == 10


def test_content_length_rejects_malformed_negative_and_duplicate_values():
    for value in (["-1"], ["abc"], ["1.5"], [""], ["0x10"]):
        error = pytest.raises(server.RequestError, server._parse_content_length, value, None)
        assert error.value.status == 400, value
    duplicate = pytest.raises(server.RequestError, server._parse_content_length, ["4", "4"], None)
    assert duplicate.value.status == 400


def test_content_length_rejects_oversized_bodies():
    error = pytest.raises(server.RequestError, server._parse_content_length, [str(server.MAX_BODY_BYTES + 1)], None)
    assert error.value.status == 413
    assert error.value.code == "payload_too_large"


def test_chunked_bodies_are_rejected():
    error = pytest.raises(server.RequestError, server._parse_content_length, [], "chunked")
    assert error.value.status == 411


def test_body_decoding_rejects_malformed_payloads():
    assert server._decode_body(b'{"prompt": "hi"}') == {"prompt": "hi"}
    for payload in (b"{not json", b"[]", b'"text"', b"\xff\xfe"):
        error = pytest.raises(server.RequestError, server._decode_body, payload)
        assert error.value.status == 400, payload


# ---------------------------------------------------------------------------
# SSE connection limiting
# ---------------------------------------------------------------------------


def test_sse_limiter_enforces_global_and_per_session_caps():
    limiter = server.SseLimiter(max_total=3, max_per_session=2)
    assert limiter.acquire("a") is True
    assert limiter.acquire("a") is True
    assert limiter.acquire("a") is False  # per-session cap
    assert limiter.acquire("b") is True
    assert limiter.acquire("c") is False  # global cap
    limiter.release("a")
    assert limiter.acquire("a") is True
    assert limiter.active == 3


def test_sse_limiter_releases_on_disconnect_and_is_idempotent():
    limiter = server.SseLimiter(max_total=1, max_per_session=1)
    assert limiter.acquire("s") is True
    limiter.release("s")
    assert limiter.active == 0
    limiter.release("s")
    limiter.release("unknown")
    assert limiter.active == 0
    assert limiter.acquire("t") is True


# ---------------------------------------------------------------------------
# Ingestion delete keeps the source registry consistent
# ---------------------------------------------------------------------------


def _write_document(corpus, source_id: str) -> None:
    doc_dir = corpus / source_id
    doc_dir.mkdir(parents=True)
    (doc_dir / "csl.json").write_text(json.dumps({"id": source_id, "title": source_id}), encoding="utf-8")
    (doc_dir / "document.json").write_text(
        json.dumps({"nodes": [{"node_id": f"{source_id}:1", "source_id": source_id, "text": "text"}]}),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_delete_document_removes_registry_entries(tmp_path):
    corpus = tmp_path / "corpus"
    _write_document(corpus, "king")
    _write_document(corpus, "other")
    registry = tmp_path / ".shutong" / "source-registry.json"
    registry.parent.mkdir()
    registry.write_text(
        json.dumps(
            {
                "king": {"document_path": str(corpus / "king"), "merkle_root": "abc"},
                "stale": {"document_path": str(corpus / "king")},
                "other": {"document_path": str(corpus / "other")},
            }
        ),
        encoding="utf-8",
    )

    result = await ingest.delete_document({"csl_id": "king"}, str(corpus))

    assert result["status"] == "ok"
    assert result["csl_id"] == "king"
    assert sorted(result["registry_removed"]) == ["king", "stale"]
    assert not (corpus / "king").exists()
    assert (corpus / "other").exists()
    remaining = json.loads(registry.read_text(encoding="utf-8"))
    assert set(remaining) == {"other"}


@pytest.mark.asyncio
async def test_unknown_delete_leaves_registry_untouched(tmp_path):
    corpus = tmp_path / "corpus"
    _write_document(corpus, "king")
    registry = tmp_path / ".shutong" / "source-registry.json"
    registry.parent.mkdir()
    original = {"king": {"document_path": str(corpus / "king")}}
    registry.write_text(json.dumps(original), encoding="utf-8")

    result = await ingest.delete_document({"csl_id": "missing"}, str(corpus))

    assert result["status"] == "error" and result["error_code"] == "not_found"
    assert json.loads(registry.read_text(encoding="utf-8")) == original


@pytest.mark.asyncio
async def test_delete_refuses_paths_outside_the_corpus_root(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    keep = outside / "keep.txt"
    keep.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(
        ingest,
        "_match_source",
        lambda loader, csl_id: {"source_id": csl_id, "doc_dir": str(outside), "csl": {}},
    )

    result = await ingest.delete_document({"csl_id": "outside"}, str(corpus))

    assert result["status"] == "error" and result["error_code"] == "outside_corpus"
    assert keep.exists()


def test_malformed_registry_is_ignored_on_delete(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    registry = tmp_path / ".shutong" / "source-registry.json"
    registry.parent.mkdir()
    registry.write_text("{not json", encoding="utf-8")

    assert ingest._forget_source(str(corpus), {"king"}, corpus.resolve() / "king") == []
    assert registry.read_text(encoding="utf-8") == "{not json"


def test_dot_corpus_roots_keep_project_state_inside_current_directory(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    (project / "document.json").write_text("{}", encoding="utf-8")

    ingest._record_source(".", "source", None, str(project / "document.json"), "root", False)
    ingest._write_status(".", {"status": "ok"})

    registry = project / ".shutong" / "source-registry.json"
    status = project / ".shutong" / "ingestion-status.json"
    assert registry.is_file()
    assert status.is_file()
    assert papers.project_root(".") == project
    assert not (tmp_path / ".shutong").exists()
