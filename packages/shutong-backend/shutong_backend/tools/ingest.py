"""Ingestion tools — ingest, status, delete."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Lazy imports — avoid triggering heavy transitive deps (dspy, paddle, etc.) at module level


def _archive_raw(source: str, library_root: str | None) -> str | None:
    path = Path(source)
    if library_root is None or not path.is_file():
        return None
    destination = Path(library_root) / "raw" / f"{hashlib.sha256(path.read_bytes()).hexdigest()[:16]}-{path.name}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copy2(path, destination)
    return str(destination)


def _record_source(corpus_root: str, source_id: str, raw_path: str | None, document_path: str | None, merkle_root: str | None, is_primary: bool) -> None:
    path = Path(corpus_root).resolve().parent / ".shutong" / "source-registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    records = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    records[source_id] = {"raw_path": raw_path, "document_path": document_path, "merkle_root": merkle_root, "role": "primary" if is_primary else "unknown"}
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _status_path(corpus_root: str) -> Path:
    return Path(corpus_root).resolve().parent / ".shutong" / "ingestion-status.json"


def _llm_model() -> str:
    model = os.environ.get("SHUTONG_LLM_MODEL", "glm-5.3-flash:cloud")
    return model if "/" in model else f"{os.environ.get('SHUTONG_LLM_PROVIDER', 'ollama')}/{model}"


def _write_status(corpus_root: str, payload: dict[str, Any]) -> None:
    path = _status_path(corpus_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**payload, "updated_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _existing_ingestion(source: str, corpus_root: str) -> dict[str, Any] | None:
    source_path = Path(source).resolve()
    for output_path in Path(corpus_root).glob("*/ingestion_output.json"):
        try:
            result = json.loads(output_path.read_text(encoding="utf-8"))
            document = result.get("sub_pipeline_outputs", {}).get("document_json", {})
            if Path(document.get("metadata", {}).get("source_path", "")).resolve() != source_path:
                continue
            csl = result.get("standardized_csl_json", {})
            return {
                "status": "ok",
                "document_path": str(output_path.parent),
                "merkle_root": csl.get("merkle_root"),
                "node_count": len(document.get("nodes", [])),
                "doc_type": csl.get("type") or csl.get("source_type"),
                "csl_id": csl.get("id"),
            }
        except (OSError, json.JSONDecodeError):
            continue
    return None


async def ingest(args: dict[str, Any], corpus_root: str, library_root: str | None = None) -> dict[str, Any]:
    from citeindex.ingestion.master import CiteIndexIngestionOrchestrator
    from citeindex.ingestion.models import IngestionConfig

    existing = _existing_ingestion(args["source"], corpus_root)
    if existing:
        raw_path = _archive_raw(args["source"], library_root)
        if existing["csl_id"]:
            _record_source(corpus_root, existing["csl_id"], raw_path, existing["document_path"], existing["merkle_root"], args.get("is_primary", False))
        existing["raw_path"] = raw_path
        _write_status(corpus_root, existing)
        return existing

    config = IngestionConfig(
        llm_model=_llm_model(),
        pageindex_model=_llm_model(),
        text_direction=args.get("text_direction", "horizontal"),
        lang=args.get("lang", "auto"),
        doc_type_override=args.get("doc_type"),
        is_primary=args.get("is_primary", False),
    )
    _write_status(corpus_root, {"status": "running", "source": args["source"]})
    orchestrator = CiteIndexIngestionOrchestrator(corpus_root=corpus_root)
    try:
        result = await asyncio.to_thread(orchestrator.ingest, args["source"], config)
    except Exception as exc:
        payload = {"status": "error", "error_code": "ingestion_failed", "message": str(exc)}
        _write_status(corpus_root, payload)
        return payload
    if result.get("status") != "ok":
        _write_status(corpus_root, result)
        return result
    csl = result.get("standardized_csl_json", {})
    document_json = result.get("sub_pipeline_outputs", {}).get("document_json") or {}
    node_count = len(document_json.get("nodes", []))
    if not node_count:
        for page in document_json.get("pages", []):
            node_count += len(page.get("paragraphs", []))
            for column in page.get("columns", []):
                node_count += len(column.get("paragraphs", []))
    payload = {
        "status": "ok",
        "document_path": result.get("document_path"),
        "merkle_root": csl.get("merkle_root"),
        "node_count": node_count,
        "doc_type": csl.get("type") or csl.get("source_type"),
        "csl_id": csl.get("id"),
    }
    if payload["csl_id"]:
        raw_path = _archive_raw(args["source"], library_root)
        _record_source(corpus_root, payload["csl_id"], raw_path, payload["document_path"], payload["merkle_root"], args.get("is_primary", False))
        payload["raw_path"] = raw_path
    _write_status(corpus_root, payload)
    return payload


async def ingest_status(_args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    path = _status_path(corpus_root)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"status": "idle"}


async def delete_document(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    from shutong_backend.agents.corpus_loader import CorpusLoader

    loader = CorpusLoader(corpus_root)
    loader.load()
    csl_id = args["csl_id"]
    source = _match_source(loader, csl_id)
    if source is None:
        return {"status": "error", "error_code": "not_found", "message": f"Unknown document: {csl_id}"}
    doc_dir = Path(source.get("doc_dir", ""))
    if not doc_dir.exists():
        return {"status": "error", "error_code": "missing_directory", "message": str(doc_dir)}
    shutil.rmtree(doc_dir)
    return {"status": "ok", "deleted_path": str(doc_dir), "csl_id": source.get("source_id", "")}


def _match_source(loader, csl_id: str) -> dict[str, Any] | None:
    for source in loader.sources:
        source_id = source.get("source_id")
        csl = source.get("csl", {})
        if csl_id in {source_id, csl.get("id"), source.get("doc_hash"), source.get("doc_dir")}:
            return source
    return None
