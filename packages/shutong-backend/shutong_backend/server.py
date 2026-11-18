"""Persistent HTTP + SSE daemon for the Shutong TUI."""

from __future__ import annotations

import argparse
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
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import parse_qs, urlparse

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
    def __init__(self, corpus_root: str, storage_dir: str, llm_model: str) -> None:
        self.corpus_root = corpus_root
        self.storage_dir = storage_dir
        self.sessions_dir = Path(storage_dir) / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.llm_model = llm_model
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

    def do_GET(self) -> None:
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
        parsed = urlparse(self.path)
        body = self._body()
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
        length = int(self.headers.get("Content-Length") or "0")
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _json(self, data: Dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _events(self, session_id: str, once: bool = False) -> None:
        session = self.daemon.create_session(session_id)
        last_id = int(self.headers.get("Last-Event-ID") or "0")
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
                try:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                except BrokenPipeError:
                    return
                continue
            for event in pending:
                last_id = int(event["id"])
                payload = f"id: {event['id']}\nevent: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n".encode("utf-8")
                try:
                    self.wfile.write(payload)
                    self.wfile.flush()
                except BrokenPipeError:
                    return
                if once and event["event"] == "done":
                    return


def _default_model() -> str:
    provider = os.environ.get("SHUTONG_LLM_PROVIDER", "ollama")
    model = os.environ.get("SHUTONG_LLM_MODEL") or os.environ.get("CITEINDEX_LLM_MODEL") or "deepseek-v4-pro:cloud"
    parsed_provider, parsed_model = parse_model(model, provider)
    return f"{parsed_provider}/{parsed_model}"


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Shutong HTTP/SSE daemon")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    corpus_root = os.environ.get("SHUTONG_CORPUS_ROOT") or os.environ.get("CITEAGENT_CORPUS_ROOT") or "corpus"
    storage_dir = os.environ.get("SHUTONG_STORAGE_DIR") or os.environ.get("CITEINDEX_STORAGE_DIR") or str(Path(corpus_root) / ".shutong")
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon = ShutongDaemon(corpus_root=corpus_root, storage_dir=storage_dir, llm_model=_default_model())  # type: ignore[attr-defined]
    print(json.dumps({"status": "listening", "host": args.host, "port": args.port}), flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
