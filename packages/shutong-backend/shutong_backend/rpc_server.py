"""Shutong backend RPC server.

NDJSON-over-stdio request/response transport for the Bun frontend.
Every request is a JSON line: {"id": "...", "method": "...", "params": {...}}
Every response is a JSON line: {"id": "...", "result": {...}} or {"id": "...", "error": {...}}
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from shutong_backend import __version__
from shutong_backend import doctor
from shutong_backend.mcp_server import TOOL_DEFINITIONS, call_tool
from shutong_backend.agents.writing.pipeline import WritingPipeline
from shutong_backend.agents.depth import DepthMeasurement
from shutong_backend.agents.devils_advocate import DevilsAdvocateAgent
from shutong_backend.agents.code_subagent import CodeSubagentAgent, detect_code_intent
from shutong_backend.agents.compact import ContextCompactor, estimate_tokens
from shutong_backend.permissions import PermissionManager
from shutong_backend.passport import MaterialPassport
from shutong_backend.graph import KnowledgeGraph
from shutong_backend.agents.review import ReviewOrchestrator
from shutong_backend.diary import SessionDiary, DiaryEntry
from shutong_backend.state import ResearchState


# ── Helpers ──────────────────────────────────────────────────────────

def _response(id_value: Any, *, result: Any | None = None, error: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"id": id_value}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    return payload


def _error_response(code: str, message: str, next_action: str = "") -> dict[str, Any]:
    return {"code": code, "message": message, "next_action": next_action}


def _get_corpus_root() -> str:
    return os.environ.get("SHUTONG_CORPUS_ROOT") or os.environ.get("CITEAGENT_CORPUS_ROOT") or "corpus"


def _get_library_root() -> str:
    return os.environ.get("SHUTONG_LIBRARY_ROOT", "library")


def _get_glossary_dir() -> str:
    return os.environ.get("SHUTONG_GLOSSARY_DIR", ".shutong/glossary")


def _storage_dir() -> str:
    return os.environ.get("SHUTONG_STORAGE_DIR", os.environ.get("CITEINDEX_STORAGE_DIR", ".shutong"))


def _llm_model() -> str:
    provider = os.environ.get("SHUTONG_LLM_PROVIDER", "ollama")
    model = os.environ.get("SHUTONG_LLM_MODEL", os.environ.get("CITEINDEX_LLM_MODEL", "deepseek-v4-pro:cloud"))
    if "/" not in model:
        model = f"{provider}/{model}"
    return model


# ── Permission manager ──────────────────────────────────────────────────

_PERMISSIONS: PermissionManager | None = None


def _get_permissions() -> PermissionManager:
    global _PERMISSIONS
    if _PERMISSIONS is None:
        perm_path = os.path.join(_storage_dir(), "permissions.json")
        _PERMISSIONS = PermissionManager(config_path=perm_path)
    return _PERMISSIONS


# ── MemPalace helpers ──────────────────────────────────────────────
import shlex

MEM_BIN = os.environ.get("MEMPALACE_BIN", "mempalace")

def _palace_path() -> str:
    return os.environ.get("SHUTONG_MEMPALACE_PALACE", ".shutong/mempalace")

async def _mempalace_run(*args: str, stdin: str | None = None) -> str:
    """Run mempalace CLI and return stdout."""
    cmd = [MEM_BIN, "--palace", _palace_path()] + list(args)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.PIPE if stdin else None,
    )
    stdout, stderr = await proc.communicate(stdin.encode() if stdin else None)
    if proc.returncode != 0:
        raise RuntimeError(f"mempalace {' '.join(args)} failed: {stderr.decode()}")
    return stdout.decode()

async def _tool_call(name: str, arguments: dict[str, Any] | None) -> Any:
    blocks = await call_tool(name, arguments)
    if not blocks:
        return {"status": "error", "error_code": "empty_response", "message": f"No payload returned for {name}"}
    text = blocks[0].get("text", "")
    return json.loads(text)


# ── Method handlers ──────────────────────────────────────────────────

async def _handle_health(params: dict[str, Any]) -> Any:
    return {
        "status": "ok",
        "backend": "shutong_backend",
        "version": __version__,
        "tool_count": len(TOOL_DEFINITIONS),
        "corpus_root": _get_corpus_root(),
        "storage_dir": _storage_dir(),
        "llm_model": _llm_model(),
    }


async def _handle_doctor(params: dict[str, Any]) -> Any:
    project_root = params.get("project_root")
    checks = doctor.collect_checks(None if not project_root else Path(project_root))
    failures = sum(1 for check in checks if not bool(check["ok"]))
    return {"status": "ok", "checks": checks, "failures": failures}


async def _handle_search(params: dict[str, Any]) -> Any:
    if params.get("mode") == "passages":
        return await _tool_call("shutong_search", dict(params))
    arguments = {
        "query": params["query"],
        "top_k": params.get("top_k", 20),
    }
    if params.get("paper_id"):
        arguments["paper_id"] = params["paper_id"]
    return await _tool_call("shutong_search", arguments)


async def _handle_chat_context(params: dict[str, Any]) -> Any:
    arguments: dict[str, Any] = {"query": params["prompt"]}
    if params.get("continuation_id"):
        arguments["continuation_id"] = params["continuation_id"]
    if params.get("user_choice"):
        arguments["user_choice"] = params["user_choice"]
    if params.get("refinement"):
        arguments["refinement"] = params["refinement"]
    return await _tool_call("shutong_chat", arguments)


async def _handle_ingest(params: dict[str, Any]) -> Any:
    arguments: dict[str, Any] = {
        "source": params["source"],
        "text_direction": params.get("text_direction", "horizontal"),
        "lang": params.get("lang", "auto"),
        "is_primary": params.get("is_primary", False),
    }
    if params.get("doc_type") is not None:
        arguments["doc_type"] = params["doc_type"]
    return await _tool_call("shutong_ingest", arguments)


async def _handle_ingest_status(params: dict[str, Any]) -> Any:
    return await _tool_call("shutong_ingest_status", {})


async def _handle_verify_document(params: dict[str, Any]) -> Any:
    return await _tool_call("shutong_verify", {
        "csl_id": params["csl_id"],
        "node_hash": params.get("node_hash"),
    })


async def _handle_verify_all(params: dict[str, Any]) -> Any:
    return await _tool_call("shutong_verify_all", {})


async def _handle_resolve_citation(params: dict[str, Any]) -> Any:
    return await _tool_call("shutong_resolve_citation", {
        "citation_key": params["citation_key"],
    })


async def _handle_translate(params: dict[str, Any]) -> Any:
    return await _tool_call("shutong_translate", {
        "source": params["source"],
        "glossary_files": params.get("glossary_files"),
    })


async def _handle_render_bilingual(params: dict[str, Any]) -> Any:
    return await _tool_call("shutong_render_bilingual", {
        "csl_id": params["csl_id"],
        "output_format": params.get("output_format", "interleaved"),
    })


async def _handle_glossary_lookup(params: dict[str, Any]) -> Any:
    return await _tool_call("shutong_glossary_lookup", {
        "terms": params["terms"],
    })


async def _handle_glossary_add(params: dict[str, Any]) -> Any:
    return await _tool_call("shutong_glossary_add", {
        "term_en": params["term_en"],
        "term_zh": params["term_zh"],
        "file": params.get("file"),
    })


async def _handle_glossary_list(params: dict[str, Any]) -> Any:
    return await _tool_call("shutong_glossary_list", {})


async def _handle_memory_search(params: dict[str, Any]) -> Any:
    return await _tool_call("shutong_memory_search", {
        "query": params["query"],
        "thread_id": params.get("thread_id"),
    })


async def _handle_memory_save(params: dict[str, Any]) -> Any:
    return await _tool_call("shutong_memory_save", {
        "title": params["title"],
        "content": params["content"],
        "tags": params.get("tags", []),
    })


async def _handle_corpus_status(params: dict[str, Any]) -> Any:
    return await _tool_call("shutong_corpus_status", {})


async def _handle_corpus_tree(params: dict[str, Any]) -> Any:
    return await _tool_call("shutong_corpus_tree", {})


async def _handle_regex_search(params: dict[str, Any]) -> Any:
    return await _tool_call("shutong_regex_search", {
        "pattern": params["pattern"],
        "field": params.get("field", "text"),
    })


async def _handle_delete_document(params: dict[str, Any]) -> Any:
    return await _tool_call("shutong_delete_document", {
        "csl_id": params["csl_id"],
    })


async def _handle_cite_render(params: dict[str, Any]) -> Any:
    return await _tool_call("shutong_cite_render", {
        "csl_id": params["csl_id"],
        "style": params.get("style", "chicago-author-date"),
    })


async def _handle_cite_tree(params: dict[str, Any]) -> Any:
    return await _tool_call("shutong_cite_tree", {
        "csl_id": params["csl_id"],
    })


async def _handle_tool_call_dispatch(params: dict[str, Any]) -> Any:
    name = params["name"]
    arguments = params.get("arguments") or {}
    if not isinstance(name, str) or not isinstance(arguments, dict):
        return {"status": "error", "error_code": "invalid_tool_call", "message": "Tool name and arguments must be a string and object."}
    permission = _get_permissions().check_with_context(name, arguments)
    if permission["status"] != "allowed":
        return permission
    return await _tool_call(name, arguments)




async def _handle_mempalace_search(params: dict[str, Any]) -> Any:
    query = params["query"]
    top_n = params.get("top_n", 10)
    output = await _mempalace_run("search", query, str(top_n))
    return {"query": query, "top_n": top_n, "results": output.strip()}


async def _handle_mempalace_wake_up(params: dict[str, Any]) -> Any:
    context = params.get("context", "")
    max_tokens = params.get("max_tokens", 300)
    output = await _mempalace_run(
        "wake-up", str(max_tokens),
        stdin=context,
    )
    return {"context": output.strip(), "tokens_approx": max_tokens}


async def _handle_mempalace_status(params: dict[str, Any]) -> Any:
    output = await _mempalace_run("status")
    return {"status": output.strip()}


async def _handle_mempalace_add(params: dict[str, Any]) -> Any:
    wing = params.get("wing", "shutong")
    room = params.get("room", "general")
    text = params["text"]
    output = await _mempalace_run("add", "--wing", wing, "--room", room, stdin=text)
    return {"added": output.strip()}


async def _handle_mempalace_instructions(params: dict[str, Any]) -> Any:
    output = await _mempalace_run("instructions")
    return {"instructions": output.strip()}


async def _handle_mempalace_compress(params: dict[str, Any]) -> Any:
    output = await _mempalace_run("compress")
    return {"compressed": output.strip()}

# ── Writing pipeline handlers ────────────────────────────────────────

async def _handle_writing_outline(params: dict[str, Any]) -> Any:
    from shutong_backend import papers
    paper_id = papers.resolve_paper_id(params, _get_corpus_root())
    sources = params.get("sources", [])
    if paper_id:
        allowed = papers.allowed_source_ids(paper_id, _get_corpus_root())
        if set(sources) - allowed:
            return {"status": "error", "error_code": "source_outside_paper", "message": "Writing sources must belong to the active paper."}
        sources = sources or sorted(allowed)
    pipeline = WritingPipeline(corpus_root=_get_corpus_root(), llm_model=_llm_model())
    topic = params.get("topic", "")
    result = pipeline.run_outline(topic=topic, sources=sources)
    if paper_id:
        result["paper_id"] = paper_id
    return result

async def _handle_writing_draft(params: dict[str, Any]) -> Any:
    pipeline = WritingPipeline(corpus_root=_get_corpus_root(), llm_model=_llm_model())
    outline = params.get("outline", {})
    result = pipeline.run_draft(outline=outline)
    return result

async def _handle_writing_style(params: dict[str, Any]) -> Any:
    pipeline = WritingPipeline(corpus_root=_get_corpus_root(), llm_model=_llm_model())
    draft = params.get("draft", {})
    result = pipeline.run_style(draft=draft)
    return result

async def _handle_writing_quality(params: dict[str, Any]) -> Any:
    pipeline = WritingPipeline(corpus_root=_get_corpus_root(), llm_model=_llm_model())
    draft = params.get("draft", {})
    result = pipeline.run_quality(draft=draft)
    return result


# ── Passport handlers ────────────────────────────────────────────────

async def _handle_passport_create(params: dict[str, Any]) -> Any:
    passport = MaterialPassport(passport_dir=os.path.join(_storage_dir(), "passport"))
    result = passport.create(
        project_name=params.get("project_name", "Untitled Project"),
        research_goals=params.get("research_goals"),
    )
    return result

async def _handle_passport_load(params: dict[str, Any]) -> Any:
    passport = MaterialPassport(passport_dir=os.path.join(_storage_dir(), "passport"))
    result = passport.load(params["passport_id"])
    return result if result else {"error": "passport not found"}

async def _handle_passport_update(params: dict[str, Any]) -> Any:
    passport = MaterialPassport(passport_dir=os.path.join(_storage_dir(), "passport"))
    result = passport.update(params["passport_id"], params.get("updates", {}))
    return result if result else {"error": "passport not found"}

async def _handle_passport_summary(params: dict[str, Any]) -> Any:
    passport = MaterialPassport(passport_dir=os.path.join(_storage_dir(), "passport"))
    text = passport.summary(params["passport_id"], max_tokens=params.get("max_tokens", 500))
    return {"summary": text}

async def _handle_passport_list(params: dict[str, Any]) -> Any:
    passport = MaterialPassport(passport_dir=os.path.join(_storage_dir(), "passport"))
    return {"passports": passport.list_passports()}


# ── Knowledge graph handlers ─────────────────────────────────────────

async def _handle_graph_query(params: dict[str, Any]) -> Any:
    graph = KnowledgeGraph(graph_dir=os.path.join(_storage_dir(), "graph"))
    node_id = params.get("node_id", "")
    depth = params.get("depth", 2)
    if not node_id:
        return {"nodes": [], "edges": []}
    return graph.query(node_id, depth=depth)

async def _handle_graph_stats(params: dict[str, Any]) -> Any:
    graph = KnowledgeGraph(graph_dir=os.path.join(_storage_dir(), "graph"))
    return graph.stats()


# ── Depth measurement handler ────────────────────────────────────────

async def _handle_depth_measure(params: dict[str, Any]) -> Any:
    dm = DepthMeasurement()
    return dm.measure(
        user_message=params.get("message", ""),
        evidence_ids=params.get("evidence_ids", []),
        retrieved_ids=params.get("retrieved_ids", []),
    )


# ── Devil's advocate handler ────────────────────────────────────────

async def _handle_devils_advocate(params: dict[str, Any]) -> Any:
    da = DevilsAdvocateAgent(llm_model=_llm_model())
    return da.challenge(
        answer_human=params.get("answer_human", ""),
        answer_machine=params.get("answer_machine", {}),
    )


# ── Peer review handler ─────────────────────────────────────────────

async def _handle_review(params: dict[str, Any]) -> Any:
    orchestrator = ReviewOrchestrator(llm_model=_llm_model())
    decision = orchestrator.review(params.get("draft", {}))
    return decision.to_dict()


# ── Code subagent handlers ────────────────────────────────────────────

async def _handle_code_subagent(params: dict[str, Any]) -> Any:
    perm = _get_permissions().check_with_context("code_subagent", params)
    if perm["status"] == "denied":
        return perm
    if perm["status"] == "needs_permission":
        return perm
    agent = CodeSubagentAgent(corpus_root=_get_corpus_root(), llm_model=_llm_model())
    return agent.run(
        instruction=params["instruction"],
        code_root=params.get("code_root"),
    )

async def _handle_code_file_read(params: dict[str, Any]) -> Any:
    perm = _get_permissions().check_with_context("shutong_file_read", params)
    if perm["status"] in ("denied", "needs_permission"):
        return perm
    from shutong_backend.tools.code import file_read
    return await file_read(params, _get_corpus_root())

async def _handle_code_file_write(params: dict[str, Any]) -> Any:
    perm = _get_permissions().check_with_context("shutong_file_write", params)
    if perm["status"] in ("denied", "needs_permission"):
        return perm
    from shutong_backend.tools.code import file_write
    return await file_write(params, _get_corpus_root())

async def _handle_code_file_edit(params: dict[str, Any]) -> Any:
    perm = _get_permissions().check_with_context("shutong_file_edit", params)
    if perm["status"] in ("denied", "needs_permission"):
        return perm
    from shutong_backend.tools.code import file_edit
    return await file_edit(params, _get_corpus_root())

async def _handle_code_file_list(params: dict[str, Any]) -> Any:
    perm = _get_permissions().check_with_context("shutong_file_list", params)
    if perm["status"] in ("denied", "needs_permission"):
        return perm
    from shutong_backend.tools.code import file_list
    return await file_list(params, _get_corpus_root())

async def _handle_code_bash(params: dict[str, Any]) -> Any:
    perm = _get_permissions().check_with_context("shutong_bash", params)
    if perm["status"] in ("denied", "needs_permission"):
        return perm
    from shutong_backend.tools.code import bash
    return await bash(params, _get_corpus_root())

async def _handle_code_grep(params: dict[str, Any]) -> Any:
    perm = _get_permissions().check_with_context("shutong_grep", params)
    if perm["status"] in ("denied", "needs_permission"):
        return perm
    from shutong_backend.tools.code import grep
    return await grep(params, _get_corpus_root())

async def _handle_code_glob(params: dict[str, Any]) -> Any:
    perm = _get_permissions().check_with_context("shutong_glob", params)
    if perm["status"] in ("denied", "needs_permission"):
        return perm
    from shutong_backend.tools.code import glob
    return await glob(params, _get_corpus_root())


# ── Context compaction handler ──────────────────────────────────────────

async def _handle_compact_context(params: dict[str, Any]) -> Any:
    messages = params.get("messages", [])
    threshold_pct = params.get("threshold_pct", 0.8)
    max_tokens = params.get("max_tokens", 4000)

    compactor = ContextCompactor(llm_model=_llm_model(), max_tokens=max_tokens)
    return compactor.compact(messages, threshold_pct=threshold_pct)


# ── Permission handlers ────────────────────────────────────────────────

async def _handle_permissions_check(params: dict[str, Any]) -> Any:
    tool_name = params.get("tool", "")
    tool_params = params.get("params", {})
    return _get_permissions().check_with_context(tool_name, tool_params)

async def _handle_permissions_list(params: dict[str, Any]) -> Any:
    return {"rules": _get_permissions().list_rules()}

async def _handle_permissions_set(params: dict[str, Any]) -> Any:
    from shutong_backend.permissions import Permission
    tool_pattern = params.get("tool_pattern", "")
    permission = params.get("permission", "ask")
    _get_permissions().set(tool_pattern, Permission(permission))
    perm_path = os.path.join(_storage_dir(), "permissions.json")
    _get_permissions().save_config(perm_path)
    return {"status": "ok", "tool_pattern": tool_pattern, "permission": permission}


# ── Diary handlers ───────────────────────────────────────────────────

async def _handle_diary_save(params: dict[str, Any]) -> Any:
    diary = SessionDiary(diary_dir=os.path.join(_storage_dir(), "diary"))
    entry = DiaryEntry(
        session_id=params.get("session_id", ""),
        topics_discussed=params.get("topics_discussed", []),
        sources_consulted=params.get("sources_consulted", []),
        key_insights=params.get("key_insights", []),
        open_questions=params.get("open_questions", []),
        depth_trend=params.get("depth_trend", "stable"),
        passport_updates=params.get("passport_updates", {}),
    )
    entry_id = diary.save(entry)
    return {"entry_id": entry_id}

async def _handle_diary_load(params: dict[str, Any]) -> Any:
    diary = SessionDiary(diary_dir=os.path.join(_storage_dir(), "diary"))
    entries = diary.load_date(params.get("date", ""))
    return {"entries": [e.to_dict() for e in entries]}

async def _handle_diary_list(params: dict[str, Any]) -> Any:
    diary = SessionDiary(diary_dir=os.path.join(_storage_dir(), "diary"))
    return {"dates": diary.list_dates()}

async def _handle_diary_recent(params: dict[str, Any]) -> Any:
    diary = SessionDiary(diary_dir=os.path.join(_storage_dir(), "diary"))
    count = params.get("count", 5)
    entries = diary.recent(count=count)
    return {"entries": [e.to_dict() for e in entries]}


# ── Academic pipeline handlers ───────────────────────────────────────

async def _handle_pipeline(params: dict[str, Any]) -> Any:
    from shutong_backend.agents.pipeline import AcademicPipeline

    pipeline = AcademicPipeline(
        corpus_root=_get_corpus_root(),
        storage_dir=_storage_dir(),
        llm_model=_llm_model(),
    )
    if params.get("pipeline_id"):
        return pipeline.resume(
            pipeline_id=params["pipeline_id"],
            user_choice=params.get("user_choice", "proceed"),
            refinement=params.get("refinement"),
        )
    return pipeline.run(
        topic=params.get("topic", ""),
        mode=params.get("mode", "full"),
        sources=params.get("sources"),
        top_k=params.get("top_k", 20),
        scope=params.get("scope", "comprehensive"),
        skip_checkpoints=params.get("skip_checkpoints", False),
    )


# ── ResearchState handlers ──────────────────────────────────────────

def _get_research_state() -> ResearchState:
    return ResearchState(storage_dir=_storage_dir())


async def _handle_state_wake_up(params: dict[str, Any]) -> Any:
    state = _get_research_state()
    return {
        "context": state.wake_up(
            passport_id=params.get("passport_id"),
            max_tokens=params.get("max_tokens", 500),
        )
    }


async def _handle_state_snapshot(params: dict[str, Any]) -> Any:
    return _get_research_state().snapshot()


async def _handle_state_record_session(params: dict[str, Any]) -> Any:
    state = _get_research_state()
    return state.record_session(
        session_id=params.get("session_id", ""),
        topics=params.get("topics", []),
        sources=params.get("sources", []),
        insights=params.get("insights", []),
        open_questions=params.get("open_questions", []),
        passport_id=params.get("passport_id"),
    )


# ── Method dispatch table ───────────────────────────────────────────

_METHODS = {
    "health": _handle_health,
    "doctor": _handle_doctor,
    "search": _handle_search,
    "chat": _handle_chat_context,
    "chat_context": _handle_chat_context,
    "ingest": _handle_ingest,
    "ingest_status": _handle_ingest_status,
    "verify_document": _handle_verify_document,
    "verify_all": _handle_verify_all,
    "resolve_citation": _handle_resolve_citation,
    "translate": _handle_translate,
    "render_bilingual": _handle_render_bilingual,
    "glossary_lookup": _handle_glossary_lookup,
    "glossary_add": _handle_glossary_add,
    "glossary_list": _handle_glossary_list,
    "memory_search": _handle_memory_search,
    "memory_save": _handle_memory_save,
    "corpus_status": _handle_corpus_status,
    "corpus_tree": _handle_corpus_tree,
    "regex_search": _handle_regex_search,
    "delete_document": _handle_delete_document,
    "cite_render": _handle_cite_render,
    "cite_tree": _handle_cite_tree,
    # Legacy: tool_call passthrough
        "mempalace_search": _handle_mempalace_search,
    "mempalace_wake_up": _handle_mempalace_wake_up,
    "mempalace_status": _handle_mempalace_status,
    "mempalace_add": _handle_mempalace_add,
    "mempalace_instructions": _handle_mempalace_instructions,
    "mempalace_compress": _handle_mempalace_compress,
    # Writing pipeline
    "writing_outline": _handle_writing_outline,
    "writing_draft": _handle_writing_draft,
    "writing_style": _handle_writing_style,
    "writing_quality": _handle_writing_quality,
    # Passport
    "passport_create": _handle_passport_create,
    "passport_load": _handle_passport_load,
    "passport_update": _handle_passport_update,
    "passport_summary": _handle_passport_summary,
    "passport_list": _handle_passport_list,
    # Knowledge graph
    "graph_query": _handle_graph_query,
    "graph_stats": _handle_graph_stats,
    # Depth measurement
    "depth_measure": _handle_depth_measure,
    # Devil's advocate
    "devils_advocate": _handle_devils_advocate,
    # Peer review
    "review": _handle_review,
    # Diary
    "diary_save": _handle_diary_save,
    "diary_load": _handle_diary_load,
    "diary_list": _handle_diary_list,
    "diary_recent": _handle_diary_recent,
    # Code subagent
    "code_subagent": _handle_code_subagent,
    "code_file_read": _handle_code_file_read,
    "code_file_write": _handle_code_file_write,
    "code_file_edit": _handle_code_file_edit,
    "code_file_list": _handle_code_file_list,
    "code_bash": _handle_code_bash,
    "code_grep": _handle_code_grep,
    "code_glob": _handle_code_glob,
    # Context compaction
    "compact_context": _handle_compact_context,
    # Permissions
    "permissions_check": _handle_permissions_check,
    "permissions_list": _handle_permissions_list,
    "permissions_set": _handle_permissions_set,
    "tool_call": _handle_tool_call_dispatch,
    # ResearchState
    "state_wake_up": _handle_state_wake_up,
    "state_snapshot": _handle_state_snapshot,
    "state_record_session": _handle_state_record_session,
    # Academic pipeline
    "pipeline": _handle_pipeline,
}


async def _handle(method: str, params: dict[str, Any]) -> Any:
    handler = _METHODS.get(method)
    if handler is None:
        raise ValueError(f"Unknown RPC method: {method}")
    return await handler(params)


# ── Server loop ──────────────────────────────────────────────────────

async def main() -> None:
    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            break
        line = line.strip()
        if not line:
            continue

        id_value: Any = None
        try:
            request = json.loads(line)
            id_value = request.get("id")
            method = request["method"]
            params = request.get("params", {})
            result = await _handle(method, params)
            message = _response(id_value, result=result)
        except Exception as exc:  # pragma: no cover - boundary protection
            message = _response(
                id_value,
                error=_error_response(
                    code=exc.__class__.__name__,
                    message=str(exc),
                    next_action="retry" if isinstance(exc, (ConnectionError, TimeoutError)) else "",
                ),
            )

        sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    asyncio.run(main())
