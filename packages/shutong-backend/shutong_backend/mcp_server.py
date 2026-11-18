"""Shutong MCP Server — thin registration layer.

Delegates all tool logic to shutong.tools.* modules.
Server name: shutong | Version: 0.4.0
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool

from shutong_backend import __version__
from shutong_backend.tools.errors import ShutongError, error_response
from shutong_backend.tools import bibliography, research, ingest, verify, translate, glossary, memory, corpus, code
from shutong_backend import analysis, papers, workspaces

SERVER_NAME = "shutong"
SERVER_VERSION = __version__

server = Server(SERVER_NAME, version=SERVER_VERSION)

_CORPUS_ROOT_ARG = "corpus"

# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------


def get_corpus_root() -> str:
    return os.environ.get("SHUTONG_CORPUS_ROOT") or os.environ.get("CITEAGENT_CORPUS_ROOT") or _CORPUS_ROOT_ARG


def get_library_root() -> str:
    return os.environ.get("SHUTONG_LIBRARY_ROOT", "library")


def get_glossary_dir() -> str:
    return os.environ.get("SHUTONG_GLOSSARY_DIR", ".shutong/glossary")


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "shutong_search",
        "description": "Search the local corpus by BM25 keyword or regular expression.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "pattern": {"type": "string"},
                "mode": {"type": "string", "enum": ["keyword", "regex"], "default": "keyword"},
                "field": {"type": "string", "enum": ["text", "title", "author", "year"], "default": "text"},
                "top_k": {"type": "integer", "default": 20},
                "paper_id": {"type": "string"},
                "library_wide": {"type": "boolean", "default": False},
            },
            "oneOf": [
                {"properties": {"mode": {"const": "keyword"}}, "required": ["query"]},
                {"properties": {"mode": {"const": "regex"}}, "required": ["pattern"]},
            ],
        },
    },
    {"name": "shutong_bibliography_search", "description": "Search public scholarly metadata APIs and scholar-supplied public catalogue/OAI-PMH/publisher endpoints; returns metadata only.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "sources": {"type": "array", "items": {"type": "string"}}, "per_source": {"type": "integer", "default": 10}, "adapters": {"type": "array", "items": {"type": "object"}}}, "required": ["query"]}},
    {"name": "shutong_bibliography_source_catalog", "description": "List available and planned scholarly source routes with access class and actual implementation status.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "shutong_paper_create", "description": "Create a project-local academic paper workspace.", "inputSchema": {"type": "object", "properties": {"paper_id": {"type": "string"}, "title": {"type": "string"}, "question": {"type": "string"}}, "required": ["paper_id", "title"]}},
    {"name": "shutong_workspace_create_project", "description": "Create a local book, article, or research project with a shared bibliography and source library.", "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}, "title": {"type": "string"}, "question": {"type": "string"}, "kind": {"type": "string", "enum": ["book", "article", "research-project"], "default": "research-project"}}, "required": ["project_id", "title"]}},
    {"name": "shutong_workspace_create_work", "description": "Create a chapter or paper inside an existing project; book chapters share that project's bibliography and sources.", "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}, "work_id": {"type": "string"}, "title": {"type": "string"}, "question": {"type": "string"}, "kind": {"type": "string", "enum": ["chapter", "paper"]}}, "required": ["project_id", "work_id", "title"]}},
    {"name": "shutong_workspace_list", "description": "List local projects, their works, and the active workspace without exposing source content.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "shutong_workspace_plan_switch", "description": "Recommend whether a new request continues, switches, or starts a project/work. Never switches automatically.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "shutong_workspace_activate", "description": "Activate a confirmed project/work. Set confirmed only after the scholar approves the switch.", "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}, "work_id": {"type": "string"}, "confirmed": {"type": "boolean", "default": False}}, "required": ["project_id", "work_id"]}},
    {"name": "shutong_paper_add_source", "description": "Assign an approved bibliography source to a paper as primary, secondary, or unknown; notes stay blocked until it is ingested.", "inputSchema": {"type": "object", "properties": {"paper_id": {"type": "string"}, "source_id": {"type": "string"}, "role": {"type": "string", "enum": ["primary", "secondary", "unknown"], "default": "unknown"}}, "required": ["paper_id", "source_id"]}},
    {"name": "shutong_paper_mark_source_ingested", "description": "Link a paper source to its existing local citeindex ingestion record.", "inputSchema": {"type": "object", "properties": {"paper_id": {"type": "string"}, "source_id": {"type": "string"}}, "required": ["paper_id", "source_id"]}},
    {"name": "shutong_paper_use", "description": "Activate a standalone paper; project works must be activated through the confirmed workspace planner.", "inputSchema": {"type": "object", "properties": {"paper_id": {"type": "string"}, "confirmed": {"type": "boolean", "default": False}}, "required": ["paper_id"]}},
    {"name": "shutong_paper_status", "description": "Show the active or named paper manifest.", "inputSchema": {"type": "object", "properties": {"paper_id": {"type": "string"}}}},
    {"name": "shutong_paper_audit", "description": "Check primary/secondary source requirements for a paper.", "inputSchema": {"type": "object", "properties": {"paper_id": {"type": "string"}}}},
    {"name": "shutong_paper_set_bibliography", "description": "Save a bibliography shortlist for scholar approval.", "inputSchema": {"type": "object", "properties": {"paper_id": {"type": "string"}, "entries": {"type": "array", "items": {"type": "object"}}}, "required": ["paper_id", "entries"]}},
    {"name": "shutong_paper_update_bibliography", "description": "Add contextual, opposing, or critical bibliography entries and return the paper to scholar approval.", "inputSchema": {"type": "object", "properties": {"paper_id": {"type": "string"}, "scope": {"type": "string", "enum": ["contextual", "opposing", "critical"]}, "entries": {"type": "array", "items": {"type": "object"}}}, "required": ["paper_id", "scope", "entries"]}},
    {"name": "shutong_paper_import_bibliography", "description": "Preserve an original BibTeX or CSL-JSON bibliography import in the local paper workspace.", "inputSchema": {"type": "object", "properties": {"paper_id": {"type": "string"}, "format": {"type": "string", "enum": ["bibtex", "csl-json"]}, "content": {"type": "string"}}, "required": ["paper_id", "format", "content"]}},
    {"name": "shutong_paper_set_source_access", "description": "Record lawful access status for a bibliography entry before ingestion.", "inputSchema": {"type": "object", "properties": {"paper_id": {"type": "string"}, "source_id": {"type": "string"}, "category": {"type": "string", "enum": ["open", "licensed", "user-provided", "metadata-only", "restricted", "unavailable"]}, "provenance": {"type": "string"}}, "required": ["paper_id", "source_id", "category"]}},
    {"name": "shutong_paper_authorize_ingestion", "description": "Record a scholar-selected individual, batch, or explicit automatic ingestion authorization.", "inputSchema": {"type": "object", "properties": {"paper_id": {"type": "string"}, "mode": {"type": "string", "enum": ["individual", "batch", "automatic"]}, "source_ids": {"type": "array", "items": {"type": "string"}}, "rule": {"type": "string"}}, "required": ["paper_id", "mode"]}},
    {"name": "shutong_paper_record_public_contact", "description": "Store a publicly published professional academic contact and its provenance locally; do not infer contact details.", "inputSchema": {"type": "object", "properties": {"paper_id": {"type": "string"}, "name": {"type": "string"}, "email": {"type": "string"}, "affiliation": {"type": "string"}, "related_work": {"type": "string"}, "provenance": {"type": "string"}, "contact_id": {"type": "string"}}, "required": ["paper_id", "name", "provenance"]}},
    {"name": "shutong_paper_draft_outreach", "description": "Create a local unsent outreach draft for a recorded public contact; Shutong never sends correspondence.", "inputSchema": {"type": "object", "properties": {"paper_id": {"type": "string"}, "contact_id": {"type": "string"}, "body": {"type": "string"}}, "required": ["paper_id", "contact_id", "body"]}},
    {"name": "shutong_paper_approve_bibliography", "description": "Record the scholar's bibliography decision; only approve unlocks source ingestion.", "inputSchema": {"type": "object", "properties": {"paper_id": {"type": "string"}, "decision": {"type": "string", "enum": ["approve", "narrow", "expand", "reject", "correct-classification"], "default": "approve"}, "reason": {"type": "string"}}, "required": ["paper_id"]}},
    {"name": "shutong_paper_add_note", "description": "Create a note from an approved, ingested source with a corpus locator.", "inputSchema": {"type": "object", "properties": {"paper_id": {"type": "string"}, "source_id": {"type": "string"}, "locator": {"type": "string"}, "content": {"type": "string"}, "note_id": {"type": "string"}}, "required": ["paper_id", "source_id", "locator", "content"]}},
    {"name": "shutong_paper_search_notes", "description": "Find a keyword or phrase in private paper notes with source/locator context.", "inputSchema": {"type": "object", "properties": {"paper_id": {"type": "string"}, "query": {"type": "string"}, "context": {"type": "integer", "default": 120}}, "required": ["paper_id", "query"]}},
    {"name": "shutong_paper_analyze_text_reuse", "description": "Find repeated private-note passages for review; it is not a plagiarism verdict.", "inputSchema": {"type": "object", "properties": {"paper_id": {"type": "string"}, "minimum_words": {"type": "integer", "default": 8}}, "required": ["paper_id"]}},
    {"name": "shutong_paper_verify_note", "description": "Record the Verifier's evidence check for a note; only verified notes can satisfy the drafting gate.", "inputSchema": {"type": "object", "properties": {"paper_id": {"type": "string"}, "note_id": {"type": "string"}, "evidence": {"type": "string"}}, "required": ["paper_id", "note_id", "evidence"]}},
    {"name": "shutong_paper_add_claim", "description": "Create a paper claim backed by one or more verified note IDs.", "inputSchema": {"type": "object", "properties": {"paper_id": {"type": "string"}, "text": {"type": "string"}, "note_ids": {"type": "array", "items": {"type": "string"}}, "claim_id": {"type": "string"}}, "required": ["paper_id", "text", "note_ids"]}},
    {"name": "shutong_paper_verify_claim", "description": "Record the Verifier's claim-evidence alignment report before a claim can be drafted.", "inputSchema": {"type": "object", "properties": {"paper_id": {"type": "string"}, "claim_id": {"type": "string"}, "evidence": {"type": "string"}}, "required": ["paper_id", "claim_id", "evidence"]}},
    {"name": "shutong_paper_draft_context", "description": "Return verified paper claims only after all evidence gates pass and the scholar explicitly requests a draft.", "inputSchema": {"type": "object", "properties": {"paper_id": {"type": "string"}, "draft_requested": {"type": "boolean", "default": False}}, "required": ["paper_id"]}},
    {"name": "shutong_paper_export_docx", "description": "Export scholar-approved draft Markdown to DOCX only after the paper evidence gates pass.", "inputSchema": {"type": "object", "properties": {"paper_id": {"type": "string"}, "draft": {"type": "string"}, "filename": {"type": "string", "default": "draft"}, "draft_requested": {"type": "boolean", "default": False}}, "required": ["paper_id", "draft"]}},
    {"name": "shutong_paper_record_verifier_report", "description": "Save a local pass, fail, or uncertain Verifier report with its evidence and residual risk.", "inputSchema": {"type": "object", "properties": {"paper_id": {"type": "string"}, "outcome": {"type": "string", "enum": ["pass", "fail", "uncertain"]}, "scope": {"type": "string"}, "evidence": {"type": "string"}, "defect": {"type": "string"}, "residual_risk": {"type": "string"}, "report_id": {"type": "string"}}, "required": ["paper_id", "outcome"]}},
    {"name": "shutong_paper_override_verifier_report", "description": "Append a scholar reason and residual risk when overriding a fail or uncertain verifier report.", "inputSchema": {"type": "object", "properties": {"paper_id": {"type": "string"}, "report_id": {"type": "string"}, "reason": {"type": "string"}, "residual_risk": {"type": "string"}}, "required": ["paper_id", "report_id", "reason"]}},
    {
        "name": "shutong_chat",
        "description": "Run the full citeindex chat pipeline over the local corpus.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "shutong_corpus_status",
        "description": "Return corpus document count, node count, and latest ingestion time.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "shutong_corpus_tree",
        "description": "Return a document-oriented view of the current corpus.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "shutong_regex_search",
        "description": "Regex search across corpus nodes or metadata.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "field": {"type": "string", "default": "text"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "shutong_ingest",
        "description": "Ingest a document, URL, or media file into the corpus.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "is_primary": {"type": "boolean", "default": False},
                "text_direction": {"type": "string", "default": "horizontal"},
                "lang": {"type": "string", "default": "auto"},
                "doc_type": {"type": ["string", "null"], "default": None},
            },
            "required": ["source"],
        },
    },
    {
        "name": "shutong_ingest_status",
        "description": "Return ingestion status for the current process.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "shutong_delete_document",
        "description": "Delete a document directory from the local corpus.",
        "inputSchema": {
            "type": "object",
            "properties": {"csl_id": {"type": "string"}},
            "required": ["csl_id"],
        },
    },
    {
        "name": "shutong_verify",
        "description": "Verify a document/node or the complete corpus Merkle integrity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "csl_id": {"type": "string"},
                "node_hash": {"type": ["string", "null"], "default": None},
                "mode": {"type": "string", "enum": ["node", "all"], "default": "node"},
            },
            "oneOf": [
                {"properties": {"mode": {"const": "node"}}, "required": ["csl_id"]},
                {"properties": {"mode": {"const": "all"}}},
            ],
        },
    },
    {
        "name": "shutong_verify_all",
        "description": "Verify every loaded document in the corpus.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "shutong_resolve_citation",
        "description": "Resolve a source id, CSL id, or Chicago-style author-year key to a corpus document.",
        "inputSchema": {
            "type": "object",
            "properties": {"citation_key": {"type": "string"}},
            "required": ["citation_key"],
        },
    },
    {
        "name": "shutong_translate",
        "description": "Translate a corpus document, file path, or plain text into bilingual Markdown.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "glossary_files": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["source"],
        },
    },
    {
        "name": "shutong_translate_url",
        "description": "Ingest a URL and translate it in one step.",
        "inputSchema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "shutong_render_bilingual",
        "description": "Return the existing bilingual output path for a translated document.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "csl_id": {"type": "string"},
                "output_format": {"type": "string", "default": "interleaved"},
            },
            "required": ["csl_id"],
        },
    },
    {
        "name": "shutong_glossary_lookup",
        "description": "Look up glossary terms across all active glossary files.",
        "inputSchema": {
            "type": "object",
            "properties": {"terms": {"type": "array", "items": {"type": "string"}}},
            "required": ["terms"],
        },
    },
    {
        "name": "shutong_glossary_add",
        "description": "Add one EN→ZH glossary entry.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "term_en": {"type": "string"},
                "term_zh": {"type": "string"},
                "file": {"type": ["string", "null"], "default": None},
            },
            "required": ["term_en", "term_zh"],
        },
    },
    {
        "name": "shutong_glossary_list",
        "description": "List glossary entries grouped by file.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "shutong_glossary_load",
        "description": "Copy an external glossary JSON file into the active glossary directory.",
        "inputSchema": {
            "type": "object",
            "properties": {"filepath": {"type": "string"}},
            "required": ["filepath"],
        },
    },
    {
        "name": "shutong_memory_search",
        "description": "Search saved memory entries.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["query"],
        },
    },
    {
        "name": "shutong_memory_list",
        "description": "List saved memory threads with entry counts and timestamps.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 20}},
        },
    },
    {
        "name": "shutong_memory_save",
        "description": "Save a named note to the local memory store.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["title", "content"],
        },
    },
    {
        "name": "shutong_cite_render",
        "description": "Render a citation from stored CSL data.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "csl_id": {"type": "string"},
                "style": {"type": "string", "default": "chicago-author-date"},
            },
            "required": ["csl_id"],
        },
    },
    {
        "name": "shutong_cite_tree",
        "description": "Return the stored Merkle tree for one document.",
        "inputSchema": {
            "type": "object",
            "properties": {"csl_id": {"type": "string"}},
            "required": ["csl_id"],
        },
    },
    # ── Code tools ─────────────────────────────────────────────────────
    {
        "name": "shutong_file_read",
        "description": "Read file contents with optional line range.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "default": 1},
                "end_line": {"type": "integer"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "shutong_file_write",
        "description": "Write or create a file with the given contents.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "shutong_file_edit",
        "description": "Edit file by exact string replacement.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
                "replace_all": {"type": "boolean", "default": False},
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "shutong_file_list",
        "description": "List directory contents.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "default": "."}},
        },
    },
    {
        "name": "shutong_bash",
        "description": "Execute a shell command with timeout.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "default": 30},
                "workdir": {"type": "string"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "shutong_grep",
        "description": "Search file contents by regex pattern.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string", "default": "."},
                "case_insensitive": {"type": "boolean", "default": True},
                "max_results": {"type": "integer", "default": 50},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "shutong_glob",
        "description": "Find files by name pattern.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string", "default": "."},
                "max_results": {"type": "integer", "default": 100},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "shutong_state_wake_up",
        "description": "Return compact cross-session research context (passport + diary + graph) for injection at session start.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "passport_id": {"type": "string"},
                "max_tokens": {"type": "integer", "default": 500},
            },
        },
    },
    {
        "name": "shutong_state_snapshot",
        "description": "Return a unified snapshot of all research state (passports, graph, diary, memory).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "shutong_state_record_session",
        "description": "Record a session across diary and passport in one call.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "topics": {"type": "array", "items": {"type": "string"}},
                "sources": {"type": "array", "items": {"type": "string"}},
                "insights": {"type": "array", "items": {"type": "string"}},
                "open_questions": {"type": "array", "items": {"type": "string"}},
                "passport_id": {"type": "string"},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "shutong_pipeline",
        "description": "Run the academic pipeline. When paper_id is supplied, return only its gated verified-claim draft context; the generic raw-retrieval pipeline is not used for paper drafting.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "mode": {"type": "string", "enum": ["research", "outline", "draft", "review", "full"], "default": "full"},
                "sources": {"type": "array", "items": {"type": "string"}},
                "top_k": {"type": "integer", "default": 20},
                "scope": {"type": "string", "default": "comprehensive"},
                "skip_checkpoints": {"type": "boolean", "default": False},
                "pipeline_id": {"type": "string"},
                "user_choice": {"type": "string", "enum": ["proceed", "refine", "abort"]},
                "refinement": {"type": "string"},
                "paper_id": {"type": "string"},
                "draft_requested": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "shutong_status",
        "description": "Unified visibility: corpus health, Merkle integrity, and research state (passports, graph, diary, memory) in one call.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

# Public conductor surface. Removed names have no handler and return
# ``unknown_tool``; there are no compatibility aliases.
_PUBLIC_NAMES = {
    "shutong_analysis",
    "shutong_status", "shutong_state_wake_up", "shutong_state_snapshot", "shutong_state_record_session",
    "shutong_bibliography_search", "shutong_bibliography_source_catalog", "shutong_ingest", "shutong_ingest_status",
    "shutong_delete_document", "shutong_search", "shutong_verify", "shutong_paper_audit",
    "shutong_paper_export_docx", "shutong_paper_status", "shutong_paper_use",
}
_GROUP_ACTIONS = {
    "shutong_workspace": ("create_paper", "create_project", "create_work", "list", "plan_switch", "activate"),
    "shutong_bibliography": ("set", "update", "import", "approve"),
    "shutong_source": ("set_access", "authorize", "add", "mark_ingested"),
    "shutong_note": ("add", "search", "verify"),
    "shutong_claim": ("add", "verify"),
    "shutong_corpus": ("status", "tree"),
    "shutong_citation": ("resolve", "render", "tree"),
    "shutong_memory": ("search", "list", "save"),
    "shutong_outreach": ("record_contact", "draft"),
    "shutong_verifier_report": ("record", "override"),
}

# Required fields are enforced both in the published JSON schema and at the
# dispatch boundary. This keeps action payloads closed even for MCP clients
# that do not validate tool schemas themselves.
_GROUP_REQUIRED = {
    "shutong_workspace": {"create_paper": ("paper_id", "title"), "create_project": ("project_id", "title"), "create_work": ("project_id", "work_id", "title"), "list": (), "plan_switch": ("query",), "activate": ("project_id", "work_id")},
    "shutong_bibliography": {"set": ("paper_id", "entries"), "update": ("paper_id", "scope", "entries"), "import": ("paper_id", "format", "content"), "approve": ("paper_id",)},
    "shutong_source": {"set_access": ("paper_id", "source_id", "category"), "authorize": ("paper_id", "mode"), "add": ("paper_id", "source_id"), "mark_ingested": ("paper_id", "source_id")},
    "shutong_note": {"add": ("paper_id", "source_id", "locator", "claim", "evidence", "confidence", "tags"), "search": ("paper_id", "query"), "verify": ("paper_id", "note_id", "evidence")},
    "shutong_claim": {"add": ("paper_id", "text", "note_ids"), "verify": ("paper_id", "claim_id", "evidence")},
    "shutong_corpus": {"status": (), "tree": ()},
    "shutong_citation": {"resolve": ("citation_key",), "render": ("csl_id",), "tree": ("csl_id",)},
    "shutong_memory": {"search": ("query",), "list": (), "save": ("title", "content")},
    "shutong_outreach": {"record_contact": ("paper_id", "name", "provenance"), "draft": ("paper_id", "contact_id", "body")},
    "shutong_verifier_report": {"record": ("paper_id", "outcome"), "override": ("paper_id", "report_id", "reason")},
}

_GROUP_PROPERTIES = {
    "shutong_note": {
        "source_id": {"type": "string"},
        "locator": {"type": "string"},
        "claim": {"type": "string"},
        "evidence": {"type": "string"},
        "confidence": {"type": "string", "enum": ["known", "probable", "speculative"]},
        "tags": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "note_id": {"type": "string"},
        "analysis_id": {"type": "string"},
        "paper_id": {"type": "string"},
        "query": {"type": "string"},
    },
}


def _group_schema(name: str, actions: tuple[str, ...]) -> dict[str, Any]:
    return {
        "type": "object",
        "oneOf": [
            {
                "properties": {"action": {"const": action}, **_GROUP_PROPERTIES.get(name, {})},
                "required": ["action", *_GROUP_REQUIRED[name][action]],
            }
            for action in actions
        ],
    }


TOOL_DEFINITIONS = [tool for tool in TOOL_DEFINITIONS if tool["name"] in _PUBLIC_NAMES] + [
    {"name": name, "description": f"Shutong {name.removeprefix('shutong_')} workflow actions.", "inputSchema": _group_schema(name, actions)}
    for name, actions in _GROUP_ACTIONS.items()
]
TOOL_DEFINITIONS.append({"name": "shutong_analysis", "description": "Run paper-scoped concordance, collocations, contextual sentiment evidence, exact quotation checks or source text reuse; retrieve, annotate and review saved provenance records.", "inputSchema": analysis.SCHEMA})


# ---------------------------------------------------------------------------
# list_tools handler
# ---------------------------------------------------------------------------


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name=tool["name"], description=tool["description"], inputSchema=tool["inputSchema"])
        for tool in TOOL_DEFINITIONS
    ]


# ---------------------------------------------------------------------------
# call_tool handler — dispatch to tool modules
# ---------------------------------------------------------------------------


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[dict[str, Any]]:
    arguments = arguments or {}
    handler = _HANDLERS.get(name)
    if handler is None:
        payload = error_response("unknown_tool", f"Unknown tool: {name}", "Check available tools with list_tools")
    else:
        try:
            payload = await handler(arguments)
        except ShutongError as exc:
            payload = error_response(exc.error_code, exc.message, exc.next_action)
        except Exception as exc:  # pragma: no cover - tool boundary
            payload = error_response(exc.__class__.__name__, str(exc), "Check input parameters and try again")
    return [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]


# ---------------------------------------------------------------------------
# Handler wrappers — delegate to tool modules
# ---------------------------------------------------------------------------


async def _handle_analysis(args: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(analysis.dispatch, args, get_corpus_root())


async def _handle_search(args: dict[str, Any]) -> dict[str, Any]:
    mode = args.pop("mode", "keyword")
    if mode == "regex":
        if not args.get("pattern"):
            raise ShutongError("invalid_input", "Regex search requires pattern.")
        return await research.regex_search(args, get_corpus_root())
    if mode != "keyword" or not args.get("query"):
        raise ShutongError("invalid_input", "Keyword search requires query.")
    return await research.search(args, get_corpus_root())


async def _handle_chat(args: dict[str, Any]) -> dict[str, Any]:
    return await research.chat(args, get_corpus_root())


async def _handle_regex_search(args: dict[str, Any]) -> dict[str, Any]:
    return await research.regex_search(args, get_corpus_root())


async def _handle_corpus_status(args: dict[str, Any]) -> dict[str, Any]:
    return await corpus.corpus_status(args, get_corpus_root())


async def _handle_corpus_tree(args: dict[str, Any]) -> dict[str, Any]:
    return await corpus.corpus_tree(args, get_corpus_root())


async def _handle_ingest(args: dict[str, Any]) -> dict[str, Any]:
    return await ingest.ingest(args, get_corpus_root(), get_library_root())


async def _handle_ingest_status(args: dict[str, Any]) -> dict[str, Any]:
    return await ingest.ingest_status(args, get_corpus_root())


async def _handle_delete_document(args: dict[str, Any]) -> dict[str, Any]:
    return await ingest.delete_document(args, get_corpus_root())


async def _handle_verify(args: dict[str, Any]) -> dict[str, Any]:
    mode = args.pop("mode", "node")
    if mode == "all":
        return await verify.verify_all(args, get_corpus_root())
    if mode != "node" or not args.get("csl_id"):
        raise ShutongError("invalid_input", "Node verification requires csl_id.")
    return await verify.verify(args, get_corpus_root())


async def _handle_verify_all(args: dict[str, Any]) -> dict[str, Any]:
    return await verify.verify_all(args, get_corpus_root())


async def _handle_resolve_citation(args: dict[str, Any]) -> dict[str, Any]:
    return await verify.resolve_citation(args, get_corpus_root())


async def _handle_translate(args: dict[str, Any]) -> dict[str, Any]:
    return await translate.translate(args, get_corpus_root(), get_library_root(), get_glossary_dir())


async def _handle_translate_url(args: dict[str, Any]) -> dict[str, Any]:
    return await translate.translate_url(args, get_corpus_root(), get_library_root(), get_glossary_dir())


async def _handle_render_bilingual(args: dict[str, Any]) -> dict[str, Any]:
    return await translate.render_bilingual(args, get_library_root())


async def _handle_glossary_lookup(args: dict[str, Any]) -> dict[str, Any]:
    return await glossary.glossary_lookup(args, get_glossary_dir())


async def _handle_glossary_add(args: dict[str, Any]) -> dict[str, Any]:
    return await glossary.glossary_add(args, get_glossary_dir())


async def _handle_glossary_list(args: dict[str, Any]) -> dict[str, Any]:
    return await glossary.glossary_list(args, get_glossary_dir())


async def _handle_glossary_load(args: dict[str, Any]) -> dict[str, Any]:
    return await glossary.glossary_load(args, get_glossary_dir())


async def _handle_memory_search(args: dict[str, Any]) -> dict[str, Any]:
    return await memory.memory_search(args, get_corpus_root())


async def _handle_memory_list(args: dict[str, Any]) -> dict[str, Any]:
    return await memory.memory_list(args, get_corpus_root())


async def _handle_memory_save(args: dict[str, Any]) -> dict[str, Any]:
    return await memory.memory_save(args, get_corpus_root())


async def _handle_cite_render(args: dict[str, Any]) -> dict[str, Any]:
    return await corpus.cite_render(args, get_corpus_root())


async def _handle_cite_tree(args: dict[str, Any]) -> dict[str, Any]:
    return await corpus.cite_tree(args, get_corpus_root())

async def _handle_state_wake_up(args: dict[str, Any]) -> dict[str, Any]:
    from shutong_backend.state import ResearchState
    state = ResearchState(storage_dir=os.environ.get("SHUTONG_STORAGE_DIR", ".shutong"))
    return {"context": state.wake_up(passport_id=args.get("passport_id"), max_tokens=args.get("max_tokens", 500))}


async def _handle_state_snapshot(args: dict[str, Any]) -> dict[str, Any]:
    from shutong_backend.state import ResearchState
    state = ResearchState(storage_dir=os.environ.get("SHUTONG_STORAGE_DIR", ".shutong"))
    return state.snapshot()


async def _handle_state_record_session(args: dict[str, Any]) -> dict[str, Any]:
    from shutong_backend.state import ResearchState
    state = ResearchState(storage_dir=os.environ.get("SHUTONG_STORAGE_DIR", ".shutong"))
    return state.record_session(
        session_id=args.get("session_id", ""),
        topics=args.get("topics", []),
        sources=args.get("sources", []),
        insights=args.get("insights", []),
        open_questions=args.get("open_questions", []),
        passport_id=args.get("passport_id"),
    )


async def _handle_pipeline(args: dict[str, Any]) -> dict[str, Any]:
    if args.get("paper_id"):
        # ponytail: the legacy pipeline retrieves raw passages; paper drafting stays on verified claims until it is migrated.
        return papers.draft_context({"paper_id": args["paper_id"], "draft_requested": args.get("draft_requested", False)}, get_corpus_root())
    from shutong_backend.agents.pipeline import AcademicPipeline
    pipeline = AcademicPipeline(
        corpus_root=get_corpus_root(),
        storage_dir=os.environ.get("SHUTONG_STORAGE_DIR", ".shutong"),
        llm_model=os.environ.get("SHUTONG_LLM_MODEL", "deepseek-v4-pro:cloud"),
    )
    if args.get("pipeline_id"):
        return pipeline.resume(
            pipeline_id=args["pipeline_id"],
            user_choice=args.get("user_choice", "proceed"),
            refinement=args.get("refinement"),
        )
    return pipeline.run(
        topic=args.get("topic", ""),
        mode=args.get("mode", "full"),
        sources=args.get("sources"),
        top_k=args.get("top_k", 20),
        scope=args.get("scope", "comprehensive"),
        skip_checkpoints=args.get("skip_checkpoints", False),
    )


async def _handle_status(args: dict[str, Any]) -> dict[str, Any]:
    from shutong_backend.state import ResearchState
    from shutong_backend.tools import corpus as corpus_tools
    from shutong_backend.tools import verify as verify_tools

    corpus_root = get_corpus_root()
    storage_dir = os.environ.get("SHUTONG_STORAGE_DIR", ".shutong")

    corpus = await corpus_tools.corpus_status({}, corpus_root)
    integrity = await verify_tools.verify_all({}, corpus_root)
    state = ResearchState(storage_dir=storage_dir).snapshot()

    return {
        "corpus": corpus,
        "integrity": {
            "documents_checked": len(integrity.get("documents", [])),
            "failures": integrity.get("failures", 0),
        },
        "research_state": state,
    }


async def _handle_paper_create(args: dict[str, Any]) -> dict[str, Any]: return papers.create(args, get_corpus_root())
async def _handle_workspace_create_project(args: dict[str, Any]) -> dict[str, Any]: return workspaces.create_project(args, get_corpus_root())
async def _handle_workspace_create_work(args: dict[str, Any]) -> dict[str, Any]: return workspaces.create_work(args, get_corpus_root())
async def _handle_workspace_list(args: dict[str, Any]) -> dict[str, Any]: return workspaces.list_workspaces(args, get_corpus_root())
async def _handle_workspace_plan_switch(args: dict[str, Any]) -> dict[str, Any]: return workspaces.plan_switch(args, get_corpus_root())
async def _handle_workspace_activate(args: dict[str, Any]) -> dict[str, Any]: return workspaces.activate(args, get_corpus_root())
async def _handle_bibliography_search(args: dict[str, Any]) -> dict[str, Any]: return await asyncio.to_thread(bibliography.search_public_metadata, args)
async def _handle_bibliography_source_catalog(args: dict[str, Any]) -> dict[str, Any]: return bibliography.source_catalog(args)
async def _handle_paper_add_source(args: dict[str, Any]) -> dict[str, Any]: return papers.add_source(args, get_corpus_root())
async def _handle_paper_mark_source_ingested(args: dict[str, Any]) -> dict[str, Any]: return papers.mark_source_ingested(args, get_corpus_root())
async def _handle_paper_use(args: dict[str, Any]) -> dict[str, Any]: return papers.use(args, get_corpus_root())
async def _handle_paper_status(args: dict[str, Any]) -> dict[str, Any]: return papers.status(args, get_corpus_root())
async def _handle_paper_audit(args: dict[str, Any]) -> dict[str, Any]: return papers.audit(args, get_corpus_root())
async def _handle_paper_set_bibliography(args: dict[str, Any]) -> dict[str, Any]: return papers.set_bibliography(args, get_corpus_root())
async def _handle_paper_update_bibliography(args: dict[str, Any]) -> dict[str, Any]: return papers.update_bibliography(args, get_corpus_root())
async def _handle_paper_import_bibliography(args: dict[str, Any]) -> dict[str, Any]: return papers.import_bibliography(args, get_corpus_root())
async def _handle_paper_set_source_access(args: dict[str, Any]) -> dict[str, Any]: return papers.set_source_access(args, get_corpus_root())
async def _handle_paper_authorize_ingestion(args: dict[str, Any]) -> dict[str, Any]: return papers.authorize_ingestion(args, get_corpus_root())
async def _handle_paper_record_public_contact(args: dict[str, Any]) -> dict[str, Any]: return papers.record_public_contact(args, get_corpus_root())
async def _handle_paper_draft_outreach(args: dict[str, Any]) -> dict[str, Any]: return papers.draft_outreach(args, get_corpus_root())
async def _handle_paper_approve_bibliography(args: dict[str, Any]) -> dict[str, Any]: return papers.approve_bibliography(args, get_corpus_root())
async def _handle_paper_add_note(args: dict[str, Any]) -> dict[str, Any]: return papers.add_note(args, get_corpus_root())
async def _handle_paper_search_notes(args: dict[str, Any]) -> dict[str, Any]: return papers.search_notes(args, get_corpus_root())
async def _handle_paper_analyze_text_reuse(args: dict[str, Any]) -> dict[str, Any]: return papers.analyze_text_reuse(args, get_corpus_root())
async def _handle_paper_verify_note(args: dict[str, Any]) -> dict[str, Any]: return papers.verify_note(args, get_corpus_root())
async def _handle_paper_add_claim(args: dict[str, Any]) -> dict[str, Any]: return papers.add_claim(args, get_corpus_root())
async def _handle_paper_verify_claim(args: dict[str, Any]) -> dict[str, Any]: return papers.verify_claim(args, get_corpus_root())
async def _handle_paper_draft_context(args: dict[str, Any]) -> dict[str, Any]: return papers.draft_context(args, get_corpus_root())
async def _handle_paper_export_docx(args: dict[str, Any]) -> dict[str, Any]: return papers.export_docx(args, get_corpus_root())
async def _handle_paper_record_verifier_report(args: dict[str, Any]) -> dict[str, Any]: return papers.record_verifier_report(args, get_corpus_root())
async def _handle_paper_override_verifier_report(args: dict[str, Any]) -> dict[str, Any]: return papers.override_verifier_report(args, get_corpus_root())


_HANDLERS = {
    "shutong_search": _handle_search,
    "shutong_bibliography_search": _handle_bibliography_search,
    "shutong_bibliography_source_catalog": _handle_bibliography_source_catalog,
    "shutong_chat": _handle_chat,
    "shutong_corpus_status": _handle_corpus_status,
    "shutong_corpus_tree": _handle_corpus_tree,
    "shutong_regex_search": _handle_regex_search,
    "shutong_ingest": _handle_ingest,
    "shutong_ingest_status": _handle_ingest_status,
    "shutong_delete_document": _handle_delete_document,
    "shutong_verify": _handle_verify,
    "shutong_verify_all": _handle_verify_all,
    "shutong_resolve_citation": _handle_resolve_citation,
    "shutong_translate": _handle_translate,
    "shutong_translate_url": _handle_translate_url,
    "shutong_render_bilingual": _handle_render_bilingual,
    "shutong_glossary_lookup": _handle_glossary_lookup,
    "shutong_glossary_add": _handle_glossary_add,
    "shutong_glossary_list": _handle_glossary_list,
    "shutong_glossary_load": _handle_glossary_load,
    "shutong_memory_search": _handle_memory_search,
    "shutong_memory_list": _handle_memory_list,
    "shutong_memory_save": _handle_memory_save,
    "shutong_cite_render": _handle_cite_render,
    "shutong_cite_tree": _handle_cite_tree,
    "shutong_paper_create": _handle_paper_create,
    "shutong_workspace_create_project": _handle_workspace_create_project,
    "shutong_workspace_create_work": _handle_workspace_create_work,
    "shutong_workspace_list": _handle_workspace_list,
    "shutong_workspace_plan_switch": _handle_workspace_plan_switch,
    "shutong_workspace_activate": _handle_workspace_activate,
    "shutong_paper_add_source": _handle_paper_add_source,
    "shutong_paper_mark_source_ingested": _handle_paper_mark_source_ingested,
    "shutong_paper_use": _handle_paper_use,
    "shutong_paper_status": _handle_paper_status,
    "shutong_paper_audit": _handle_paper_audit,
    "shutong_paper_set_bibliography": _handle_paper_set_bibliography,
    "shutong_paper_update_bibliography": _handle_paper_update_bibliography,
    "shutong_paper_import_bibliography": _handle_paper_import_bibliography,
    "shutong_paper_set_source_access": _handle_paper_set_source_access,
    "shutong_paper_authorize_ingestion": _handle_paper_authorize_ingestion,
    "shutong_paper_record_public_contact": _handle_paper_record_public_contact,
    "shutong_paper_draft_outreach": _handle_paper_draft_outreach,
    "shutong_paper_approve_bibliography": _handle_paper_approve_bibliography,
    "shutong_paper_add_note": _handle_paper_add_note,
    "shutong_paper_search_notes": _handle_paper_search_notes,
    "shutong_paper_analyze_text_reuse": _handle_paper_analyze_text_reuse,
    "shutong_paper_verify_note": _handle_paper_verify_note,
    "shutong_paper_add_claim": _handle_paper_add_claim,
    "shutong_paper_verify_claim": _handle_paper_verify_claim,
    "shutong_paper_draft_context": _handle_paper_draft_context,
    "shutong_paper_export_docx": _handle_paper_export_docx,
    "shutong_paper_record_verifier_report": _handle_paper_record_verifier_report,
    "shutong_paper_override_verifier_report": _handle_paper_override_verifier_report,
    # ResearchState
    "shutong_state_wake_up": _handle_state_wake_up,
    "shutong_state_snapshot": _handle_state_snapshot,
    "shutong_state_record_session": _handle_state_record_session,
    "shutong_pipeline": _handle_pipeline,
    "shutong_status": _handle_status,
    # Code tools
    "shutong_file_read": lambda args: code.file_read(args, get_corpus_root()),
    "shutong_file_write": lambda args: code.file_write(args, get_corpus_root()),
    "shutong_file_edit": lambda args: code.file_edit(args, get_corpus_root()),
    "shutong_file_list": lambda args: code.file_list(args, get_corpus_root()),
    "shutong_bash": lambda args: code.bash(args, get_corpus_root()),
    "shutong_grep": lambda args: code.grep(args, get_corpus_root()),
    "shutong_glob": lambda args: code.glob(args, get_corpus_root()),
}

_GROUP_HANDLERS = {
    "shutong_workspace": {"create_paper": _handle_paper_create, "create_project": _handle_workspace_create_project, "create_work": _handle_workspace_create_work, "list": _handle_workspace_list, "plan_switch": _handle_workspace_plan_switch, "activate": _handle_workspace_activate},
    "shutong_bibliography": {"set": _handle_paper_set_bibliography, "update": _handle_paper_update_bibliography, "import": _handle_paper_import_bibliography, "approve": _handle_paper_approve_bibliography},
    "shutong_source": {"set_access": _handle_paper_set_source_access, "authorize": _handle_paper_authorize_ingestion, "add": _handle_paper_add_source, "mark_ingested": _handle_paper_mark_source_ingested},
    "shutong_note": {"add": _handle_paper_add_note, "search": _handle_paper_search_notes, "verify": _handle_paper_verify_note},
    "shutong_claim": {"add": _handle_paper_add_claim, "verify": _handle_paper_verify_claim},
    "shutong_corpus": {"status": _handle_corpus_status, "tree": _handle_corpus_tree},
    "shutong_citation": {"resolve": _handle_resolve_citation, "render": _handle_cite_render, "tree": _handle_cite_tree},
    "shutong_memory": {"search": _handle_memory_search, "list": _handle_memory_list, "save": _handle_memory_save},
    "shutong_outreach": {"record_contact": _handle_paper_record_public_contact, "draft": _handle_paper_draft_outreach},
    "shutong_verifier_report": {"record": _handle_paper_record_verifier_report, "override": _handle_paper_override_verifier_report},
}


_HANDLERS["shutong_analysis"] = _handle_analysis


async def _handle_group(name: str, args: dict[str, Any]) -> dict[str, Any]:
    action = args.pop("action", None)
    handler = _GROUP_HANDLERS[name].get(action)
    if handler is None:
        raise ShutongError("invalid_action", f"Unsupported {name} action: {action}")
    missing = [field for field in _GROUP_REQUIRED[name][action] if field not in args]
    if missing:
        raise ShutongError("invalid_input", f"Missing required field(s) for {name}.{action}: {', '.join(missing)}")
    return await handler(args)


for _name in _GROUP_HANDLERS:
    _HANDLERS[_name] = lambda args, name=_name: _handle_group(name, dict(args))

# Only the public conductor contract remains callable.
for _name in tuple(_HANDLERS):
    if _name not in _PUBLIC_NAMES and _name not in _GROUP_HANDLERS:
        del _HANDLERS[_name]


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--corpus-root", default="corpus")
    return parser.parse_args()


def cli() -> None:
    """Console-script entry point: parse args, then run the async server."""
    global _CORPUS_ROOT_ARG
    args = _parse_args()
    _CORPUS_ROOT_ARG = args.corpus_root
    asyncio.run(main())


if __name__ == "__main__":
    cli()
