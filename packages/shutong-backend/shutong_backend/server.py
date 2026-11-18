"""Persistent HTTP + SSE daemon for the Shutong TUI.

Local threat model: the daemon can change the global provider and start model
turns, so it always requires a bearer token (``SHUTONG_HTTP_TOKEN``) and refuses
to start without one.  It binds to loopback by default; a browser page (or
another local process) is still an attacker we care about.  Therefore:

* every route, including ``/health``, requires ``Authorization: Bearer <token>``;
* browser-originated requests must be same-origin loopback (``Origin``/``Host``
  validation) — the TUI/CLI is a non-browser client and may omit ``Origin``;
* request bodies are capped at ``MAX_BODY_BYTES`` and malformed framing is
  rejected instead of raising through the connection handler;
* concurrent SSE streams are capped globally and per session.

Binding to a non-loopback host exposes the token-guarded API to the network and
is not supported for browser clients; keep the default loopback bind.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.parse import parse_qs, urlparse, urlsplit

from shutong_backend import __version__
from shutong_backend.agents.chat import ChatPipeline
from shutong_backend.agents.corpus_loader import CorpusLoader
from shutong_backend.agents.generation import GenerationAgent
from shutong_backend.agents.indexing import IndexingAgent
from shutong_backend.agents.models import AnswerMachine
from shutong_backend.agents.query_planner import QueryPlanner
from shutong_backend.agents.retrieval import RetrievalAgent
from shutong_backend.llm import get_llm
from shutong_backend.llm.registry import list_providers, parse_model
from shutong_backend.permissions import PermissionManager


def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9\-_]", "_", value)


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
MAX_BODY_BYTES = 1024 * 1024
MAX_SSE_CONNECTIONS = 32
MAX_SSE_PER_SESSION = 4
MIN_TOKEN_LENGTH = 16


class RequestError(Exception):
    """A request that must be refused with an HTTP status, not a traceback."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _reject_request(status: int, code: str, message: str) -> RequestError:
    return RequestError(status, code, message)


def _authorize_request(authorization_values: Sequence[str], expected_token: str | None) -> RequestError | None:
    """Require ``Authorization: Bearer <token>`` for every route.

    Fails closed when the daemon has no configured token: there is no
    unauthenticated mode, because the daemon can change the global provider and
    start model turns.
    """
    if not expected_token:
        return _reject_request(HTTPStatus.UNAUTHORIZED, "unauthorized", "The daemon has no access token configured.")
    if len(authorization_values) != 1:
        return _reject_request(HTTPStatus.UNAUTHORIZED, "unauthorized", "Exactly one bearer token is required.")
    scheme, _, credential = authorization_values[0].strip().partition(" ")
    credential = credential.strip()
    if scheme.lower() != "bearer" or not credential:
        return _reject_request(HTTPStatus.UNAUTHORIZED, "unauthorized", "A bearer token is required.")
    if not hmac.compare_digest(credential.encode("utf-8"), expected_token.encode("utf-8")):
        return _reject_request(HTTPStatus.UNAUTHORIZED, "unauthorized", "Invalid access token.")
    return None


def _split_authority(value: str | None) -> tuple[str, int | None] | None:
    """Parse a ``Host``-style ``host[:port]`` value, rejecting userinfo and paths."""
    if not value:
        return None
    raw = value.strip()
    if not raw or any(char in raw for char in "/@?#"):
        return None
    try:
        parsed = urlsplit(f"//{raw}")
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if not host:
        return None
    return host.lower(), port


def _validate_local_request(
    origin: str | None,
    host_header: str | None,
    server_port: int,
    bound_host: str | None = "127.0.0.1",
    fetch_site: str | None = None,
) -> RequestError | None:
    """Refuse browser requests that are not same-origin loopback.

    Browsers attach ``Origin`` to cross-origin requests; a native TUI fetch may
    omit it.  When ``Origin`` is present it must be loopback and match both the
    listening port and the ``Host`` header.  A valid loopback ``Host`` header is
    required in every case (the TS client always sends one; HTTP/1.0 requests
    without one are refused), so DNS-rebinding pages and hand-rolled clients are
    both rejected.
    """
    host = _split_authority(host_header)

    if fetch_site and fetch_site.strip().lower() not in {"same-origin", "none"}:
        return _reject_request(HTTPStatus.FORBIDDEN, "origin_refused", "Cross-origin requests are refused.")

    if origin:
        try:
            parsed = urlsplit(origin.strip())
        except ValueError:
            return _reject_request(HTTPStatus.FORBIDDEN, "origin_refused", "Invalid Origin header.")
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return _reject_request(HTTPStatus.FORBIDDEN, "origin_refused", "Invalid Origin header.")
        if parsed.username or parsed.password:
            return _reject_request(HTTPStatus.FORBIDDEN, "origin_refused", "Invalid Origin header.")
        origin_host = parsed.hostname.lower()
        try:
            origin_port = parsed.port
        except ValueError:
            return _reject_request(HTTPStatus.FORBIDDEN, "origin_refused", "Invalid Origin header.")
        if origin_port is None:
            origin_port = 443 if parsed.scheme == "https" else 80
        if origin_host not in LOOPBACK_HOSTS:
            return _reject_request(HTTPStatus.FORBIDDEN, "origin_refused", "Only loopback origins are accepted.")
        if origin_port != server_port:
            return _reject_request(HTTPStatus.FORBIDDEN, "origin_refused", "Origin does not match the daemon port.")
        if host is None or (host[0], host[1] if host[1] is not None else 80) != (origin_host, origin_port):
            return _reject_request(HTTPStatus.FORBIDDEN, "origin_refused", "Origin does not match the Host header.")
        return None

    if host is None:
        return _reject_request(HTTPStatus.FORBIDDEN, "origin_refused", "A valid loopback Host header is required.")
    host_name, host_port = host
    if (host_port if host_port is not None else 80) != server_port:
        return _reject_request(HTTPStatus.FORBIDDEN, "origin_refused", "Host does not match the daemon port.")
    allowed_hosts = LOOPBACK_HOSTS | {(bound_host or "").strip().lower()}
    if host_name not in allowed_hosts:
        return _reject_request(HTTPStatus.FORBIDDEN, "origin_refused", "Only loopback Host headers are accepted.")
    return None


def _parse_content_length(values: Sequence[str], transfer_encoding: str | None) -> int:
    """Validate request framing before reading, so bad clients get 4xx replies."""
    if transfer_encoding and transfer_encoding.strip().lower() != "identity":
        raise _reject_request(HTTPStatus.LENGTH_REQUIRED, "length_required", "Chunked request bodies are not supported.")
    if not values:
        return 0
    if len(values) > 1:
        raise _reject_request(HTTPStatus.BAD_REQUEST, "invalid_content_length", "Send exactly one Content-Length header.")
    raw = values[0].strip()
    if not raw or not raw.isdigit():
        raise _reject_request(HTTPStatus.BAD_REQUEST, "invalid_content_length", "Content-Length must be a non-negative integer.")
    length = int(raw)
    if length > MAX_BODY_BYTES:
        raise _reject_request(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "payload_too_large", f"Request bodies are limited to {MAX_BODY_BYTES} bytes.")
    return length


def _decode_body(data: bytes) -> Dict[str, Any]:
    """Decode a JSON object body, treating malformed input as a client error."""
    try:
        body = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _reject_request(HTTPStatus.BAD_REQUEST, "invalid_json", "Request body must be UTF-8 encoded JSON.") from None
    if not isinstance(body, dict):
        raise _reject_request(HTTPStatus.BAD_REQUEST, "invalid_json", "Request body must be a JSON object.")
    return body


def _header_int(value: str | None, default: int = 0) -> int:
    if not value:
        return default
    try:
        parsed = int(value.strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


class SseLimiter:
    """Bound concurrent event streams so one client cannot exhaust the threads."""

    def __init__(self, max_total: int = MAX_SSE_CONNECTIONS, max_per_session: int = MAX_SSE_PER_SESSION) -> None:
        self.max_total = max_total
        self.max_per_session = max_per_session
        self._lock = threading.Lock()
        self._total = 0
        self._per_session: Dict[str, int] = {}

    def acquire(self, session_id: str) -> bool:
        with self._lock:
            if self._total >= self.max_total:
                return False
            if self._per_session.get(session_id, 0) >= self.max_per_session:
                return False
            self._per_session[session_id] = self._per_session.get(session_id, 0) + 1
            self._total += 1
            return True

    def release(self, session_id: str) -> None:
        with self._lock:
            count = self._per_session.get(session_id, 0)
            if count <= 0:
                return
            if count == 1:
                self._per_session.pop(session_id, None)
            else:
                self._per_session[session_id] = count - 1
            self._total = max(0, self._total - 1)

    @property
    def active(self) -> int:
        with self._lock:
            return self._total


@dataclass
class Session:
    id: str
    title: str = "New session"
    created_at: int = field(default_factory=_now_ms)
    updated_at: int = field(default_factory=_now_ms)
    messages: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    next_event_id: int = 1
    condition: threading.Condition = field(default_factory=threading.Condition)

    def append_event(self, event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        with self.condition:
            event = {"id": self.next_event_id, "event": event_type, "data": data}
            self.next_event_id += 1
            self.events.append(event)
            self.condition.notify_all()
            return event


class ShutongDaemon:
    def __init__(self, corpus_root: str, storage_dir: str, llm_model: str, http_token: str | None = None) -> None:
        self.corpus_root = corpus_root
        self.storage_dir = storage_dir
        self.sessions_dir = Path(storage_dir) / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.llm_model = llm_model
        self.http_token = http_token
        self.sse_limiter = SseLimiter()
        self.permissions = PermissionManager(config_path=str(Path(storage_dir) / "permissions.json"))
        self.sessions: Dict[str, Session] = {}
        self.lock = threading.Lock()

    def create_session(self, session_id: Optional[str] = None) -> Session:
        sid = session_id or f"s-{int(time.time()):x}-{uuid.uuid4().hex[:8]}"
        with self.lock:
            session = self.sessions.get(sid)
            if session is None:
                session = self._load_session(sid) or Session(id=sid)
                self.sessions[sid] = session
            return session

    def list_sessions(self) -> List[Dict[str, Any]]:
        for path in self.sessions_dir.glob("*.json"):
            if path.name != "_index.json":
                self.create_session(path.stem)
        metas = [self._meta(s) for s in self.sessions.values()]
        return sorted(metas, key=lambda item: item["updatedAt"], reverse=True)

    def start_message(self, session_id: str, prompt: str) -> None:
        session = self.create_session(session_id)
        threading.Thread(target=self._run_turn, args=(session, prompt), daemon=True).start()

    def _run_turn(self, session: Session, prompt: str) -> None:
        session.messages.append({"role": "user", "content": prompt, "citations": [], "timestamp": _now_ms()})
        if session.title == "New session" and prompt.strip():
            session.title = prompt.strip().replace("\n", " ")[:60]
        session.updated_at = _now_ms()
        self._save_session(session)

        try:
            result = self._stream_chat(session, prompt)
        except Exception as exc:
            message = f"LLM error: {exc}"
            session.append_event("error", {"message": message, "status": "llm_error"})
            result = {"status": "llm_error", "answer_human": message, "answer_machine": {"evidence": []}, "message": message}

        answer = str(result.get("answer_human") or result.get("message") or "")
        citations = [
            item.get("citation_rendered") or item.get("formatted_citation") or item.get("node_id")
            for item in (result.get("answer_machine", {}).get("evidence", []) if isinstance(result.get("answer_machine"), dict) else [])
        ]
        if answer:
            session.messages.append({"role": "assistant", "content": answer, "citations": [c for c in citations if c], "timestamp": _now_ms()})
            session.updated_at = _now_ms()
            self._save_session(session)
        session.append_event("done", {"result": result})

    def _stream_chat(self, session: Session, prompt: str) -> Dict[str, Any]:
        session.append_event("stage", {"name": "load_corpus", "message": "Loading corpus…"})
        loader = CorpusLoader(self.corpus_root)
        loader.load()

        session.append_event("stage", {"name": "plan_query", "message": "Planning query…"})
        planner = QueryPlanner()
        query_plan = planner.plan(prompt, csl_registry=loader.csl_registry)
        if query_plan.clarification_required:
            return ChatPipeline(corpus_root=self.corpus_root, llm_model=self.llm_model).chat(prompt, session.id)

        session.append_event("stage", {"name": "retrieve", "message": "Searching corpus…"})
        index_output = IndexingAgent().run(loader.all_nodes)
        retrieval = RetrievalAgent().run(query_plan.to_dict(), loader.all_nodes, index_output.inverted_index, loader.csl_registry)

        generator = GenerationAgent()
        evidence_items = generator._build_evidence(retrieval.ranked_nodes, loader.csl_registry, loader.merkle_registry, "chicago-author-date") if retrieval.ranked_nodes else []
        llm_prompt = self._prompt_with_evidence(prompt, evidence_items) if evidence_items else self._prompt_without_evidence(prompt)

        session.append_event("stage", {"name": "generate", "message": "Generating…"})
        provider = get_llm(self.llm_model, temperature=0.1)
        model = getattr(provider, "_default_model", "")
        chunks: List[str] = []
        for delta in provider.stream([{"role": "user", "content": llm_prompt}], model=model):
            if not delta:
                continue
            chunks.append(delta)
            session.append_event("message.part.updated", {"text": delta})
        if not chunks:
            text = provider.invoke(llm_prompt, model=model)
            chunks.append(text)
            session.append_event("message.part.updated", {"text": text})

        answer = "".join(chunks)
        machine = AnswerMachine(
            query_id=query_plan.query_id,
            answer=answer,
            evidence=[item.to_dict() for item in evidence_items],
        ).to_dict()
        result: Dict[str, Any] = {
            "status": "ok",
            "thread": session.id,
            "query_id": query_plan.query_id,
            "answer_human": answer,
            "answer_machine": machine,
            "retrieval_debug": retrieval.retrieval_debug,
        }
        return result

    @staticmethod
    def _prompt_with_evidence(user_query: str, evidence_items: Iterable[Any]) -> str:
        context_parts = []
        for item in evidence_items:
            citation = item.citation_rendered or item.citation_key
            context_parts.append(f"[{item.node_id}] ({citation}):\n{item.text}")
        context = "\n\n---\n\n".join(context_parts)
        return (
            "Based ONLY on the following evidence passages, answer the question.\n"
            "For every claim, cite the evidence using [Author, Year] format.\n"
            "If the evidence is insufficient, say so.\n\n"
            f"Evidence:\n{context}\n\n"
            f"Question: {user_query}\n\nAnswer:"
        )

    @staticmethod
    def _prompt_without_evidence(user_query: str) -> str:
        return (
            "No corpus evidence was retrieved for this turn. "
            "For casual or operational prompts, answer normally and briefly. "
            "For factual scholarly claims, say exactly: "
            "\"No citation available for this claim in the current corpus.\"\n\n"
            f"User: {user_query}\n\nAssistant:"
        )

    def _session_path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{_safe_id(session_id)}.json"

    def _load_session(self, session_id: str) -> Optional[Session]:
        path = self._session_path(session_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            meta = data.get("meta", {})
            return Session(
                id=meta.get("id") or session_id,
                title=meta.get("title") or "New session",
                created_at=int(meta.get("createdAt") or _now_ms()),
                updated_at=int(meta.get("updatedAt") or _now_ms()),
                messages=data.get("messages") or [],
            )
        except Exception:
            return None

    def _save_session(self, session: Session) -> None:
        path = self._session_path(session.id)
        payload = {"meta": self._meta(session), "messages": session.messages}
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        index = {"sessions": self.list_sessions()[:100]}
        (self.sessions_dir / "_index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _meta(session: Session) -> Dict[str, Any]:
        return {
            "id": session.id,
            "title": session.title,
            "createdAt": session.created_at,
            "updatedAt": session.updated_at,
            "messageCount": len(session.messages),
        }


class Handler(BaseHTTPRequestHandler):
    server_version = "ShutongDaemon/1.0"

    @property
    def daemon(self) -> ShutongDaemon:
        return self.server.daemon  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _deny(self) -> bool:
        """Authorize and validate the request; reply and return True when refused."""
        error = _authorize_request(self.headers.get_all("Authorization") or [], self.daemon.http_token)
        if error is None:
            error = _validate_local_request(
                self.headers.get("Origin"),
                self.headers.get("Host"),
                self.server.server_address[1],  # type: ignore[attr-defined]
                self.server.server_address[0],  # type: ignore[attr-defined]
                self.headers.get("Sec-Fetch-Site"),
            )
        if error is None:
            return False
        self.close_connection = True
        headers = {"WWW-Authenticate": "Bearer"} if error.status == HTTPStatus.UNAUTHORIZED else None
        try:
            self._json({"status": "error", "code": error.code, "message": error.message}, status=error.status, headers=headers)
        except OSError:
            pass
        return True

    def do_GET(self) -> None:
        if self._deny():
            return
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json({"status": "ok", "backend": "shutong_backend", "version": __version__, "llm_model": self.daemon.llm_model})
            return
        if parsed.path == "/providers":
            self._json({**list_providers(), "current": self.daemon.llm_model})
            return
        if parsed.path == "/session":
            self._json({"sessions": self.daemon.list_sessions()})
            return
        match = re.fullmatch(r"/session/([^/]+)/event", parsed.path)
        if match:
            once = parse_qs(parsed.query).get("once", ["0"])[0] == "1"
            self._events(match.group(1), once=once)
            return
        self._json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self._deny():
            return
        try:
            body = self._body()
        except RequestError as error:
            self.close_connection = True
            try:
                self._json({"status": "error", "code": error.code, "message": error.message}, status=error.status)
            except OSError:
                pass
            return
        parsed = urlparse(self.path)
        if parsed.path == "/session":
            session = self.daemon.create_session(str(body.get("id") or "") or None)
            self._json({"session": self.daemon._meta(session)})
            return
        if parsed.path == "/provider/switch":
            provider = str(body.get("provider") or "ollama")
            model = str(body.get("model") or "")
            if not model:
                self._json({"status": "error", "message": "model is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            self.daemon.llm_model = f"{provider}/{model}" if "/" not in model else model
            self._json({"status": "ok", "llm_model": self.daemon.llm_model})
            return
        match = re.fullmatch(r"/session/([^/]+)/message", parsed.path)
        if match:
            prompt = str(body.get("prompt") or "")
            if not prompt:
                self._json({"status": "error", "message": "prompt is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            self.daemon.start_message(match.group(1), prompt)
            self._json({"status": "accepted"}, status=HTTPStatus.ACCEPTED)
            return
        self._json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def _body(self) -> Dict[str, Any]:
        length = _parse_content_length(self.headers.get_all("Content-Length") or [], self.headers.get("Transfer-Encoding"))
        if length == 0:
            return {}
        data = self.rfile.read(length)
        if len(data) != length:
            raise _reject_request(HTTPStatus.BAD_REQUEST, "truncated_body", "Request body ended before Content-Length bytes were read.")
        return _decode_body(data)

    def _json(self, data: Dict[str, Any], status: int = HTTPStatus.OK, headers: Optional[Dict[str, str]] = None) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)

    def _events(self, session_id: str, once: bool = False) -> None:
        session = self.daemon.create_session(session_id)
        last_id = _header_int(self.headers.get("Last-Event-ID"))
        limiter = self.daemon.sse_limiter
        if not limiter.acquire(session.id):
            self._json(
                {"status": "error", "code": "too_many_streams", "message": "Too many concurrent event streams."},
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            while True:
                with session.condition:
                    pending = [event for event in session.events if event["id"] > last_id]
                    if not pending:
                        session.condition.wait(timeout=15)
                        pending = [event for event in session.events if event["id"] > last_id]
                if not pending:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    continue
                for event in pending:
                    last_id = int(event["id"])
                    payload = f"id: {event['id']}\nevent: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n".encode("utf-8")
                    self.wfile.write(payload)
                    self.wfile.flush()
                    if once and event["event"] == "done":
                        return
        except (BrokenPipeError, ConnectionResetError, OSError):
            return
        finally:
            # An event stream is never reused for another request.
            self.close_connection = True
            limiter.release(session.id)


def _default_model() -> str:
    provider = os.environ.get("SHUTONG_LLM_PROVIDER", "ollama")
    model = os.environ.get("SHUTONG_LLM_MODEL") or os.environ.get("CITEINDEX_LLM_MODEL") or "deepseek-v4-pro:cloud"
    parsed_provider, parsed_model = parse_model(model, provider)
    return f"{parsed_provider}/{parsed_model}"


def _required_token() -> str:
    """Read the daemon bearer token; refuse to start unauthenticated."""
    token = (os.environ.get("SHUTONG_HTTP_TOKEN") or "").strip()
    if not token:
        raise SystemExit("SHUTONG_HTTP_TOKEN is required: the Shutong daemon does not run unauthenticated.")
    if len(token) < MIN_TOKEN_LENGTH:
        raise SystemExit(f"SHUTONG_HTTP_TOKEN must be at least {MIN_TOKEN_LENGTH} characters.")
    return token


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Shutong HTTP/SSE daemon")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address; loopback is required for browser clients.")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    http_token = _required_token()
    corpus_root = os.environ.get("SHUTONG_CORPUS_ROOT") or os.environ.get("CITEAGENT_CORPUS_ROOT") or "corpus"
    storage_dir = os.environ.get("SHUTONG_STORAGE_DIR") or os.environ.get("CITEINDEX_STORAGE_DIR") or str(Path(corpus_root) / ".shutong")
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon = ShutongDaemon(corpus_root=corpus_root, storage_dir=storage_dir, llm_model=_default_model(), http_token=http_token)  # type: ignore[attr-defined]
    print(json.dumps({"status": "listening", "host": args.host, "port": args.port}), flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
