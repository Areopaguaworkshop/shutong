"""Project/work routing for multi-paper scholarship without silent context switches."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from shutong_backend import papers
from shutong_backend.tools.errors import ShutongError

_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_PROJECT_KINDS = {"book", "article", "research-project"}
_WORK_KINDS = {"chapter", "paper"}


def _root(corpus_root: str) -> Path:
    return papers.project_root(corpus_root) / "projects"


def _path(corpus_root: str, project_id: str) -> Path:
    if not _ID.fullmatch(project_id):
        raise ShutongError("invalid_project_id", "Project IDs use lowercase letters, numbers, and hyphens.")
    return _root(corpus_root) / project_id / "project.json"


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ShutongError("project_not_found", f"Project not found: {path.parent.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, project: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def create_project(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    project_id = args["project_id"]
    if not _ID.fullmatch(project_id) or len(project_id) > 55:
        raise ShutongError("invalid_project_id", "Project IDs use lowercase letters, numbers, and hyphens and leave room for the shared source-library suffix.")
    kind = args.get("kind", "research-project")
    if kind not in _PROJECT_KINDS:
        raise ShutongError("invalid_project_kind", "Project kind must be book, article, or research-project.")
    path = _path(corpus_root, project_id)
    if path.exists():
        raise ShutongError("project_exists", f"Project already exists: {project_id}")
    source_workspace_id = f"{project_id}-sources"
    papers.create({"paper_id": source_workspace_id, "title": f"{args['title']} — shared source library", "question": args.get("question", "")}, corpus_root)
    source_path = papers._paper_path(corpus_root, source_workspace_id)
    source_workspace = papers._read(source_path)
    source_workspace["workspace_role"] = "shared-source-library"
    source_workspace["project_id"] = project_id
    papers._write(source_path, source_workspace)
    project = {"id": project_id, "title": args["title"], "question": args.get("question", ""), "kind": kind, "source_workspace_id": source_workspace_id, "works": []}
    _write(path, project)
    return {"status": "ok", "project": project, "path": str(path)}


def create_work(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    project_path = _path(corpus_root, args["project_id"])
    project = _read(project_path)
    work_id = args["work_id"]
    if not _ID.fullmatch(work_id):
        raise ShutongError("invalid_work_id", "Work IDs use lowercase letters, numbers, and hyphens.")
    kind = args.get("kind", "chapter" if project["kind"] == "book" else "paper")
    if kind not in _WORK_KINDS:
        raise ShutongError("invalid_work_kind", "Work kind must be chapter or paper.")
    if project["kind"] == "book" and kind != "chapter":
        raise ShutongError("book_requires_chapter", "Works in a book project must be chapters.")
    papers.create({"paper_id": work_id, "title": args["title"], "question": args.get("question", ""), "minimum_primary": args.get("minimum_primary", 1), "minimum_secondary": args.get("minimum_secondary", 1)}, corpus_root)
    work_path = papers._paper_path(corpus_root, work_id)
    work = papers._read(work_path)
    work.update({"project_id": project["id"], "work_kind": kind, "source_workspace_id": project["source_workspace_id"]})
    papers._write(work_path, work)
    project["works"].append({"id": work_id, "title": work["title"], "question": work["question"], "kind": kind})
    _write(project_path, project)
    return {"status": "ok", "project_id": project["id"], "work": work, "path": str(work_path)}


def list_workspaces(_args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    projects = []
    for path in sorted(_root(corpus_root).glob("*/project.json")) if _root(corpus_root).exists() else []:
        projects.append(_read(path))
    return {"status": "ok", "active": active(corpus_root), "projects": projects}


def active(corpus_root: str) -> dict[str, str] | None:
    path = papers.project_root(corpus_root) / ".shutong" / "active-workspace.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def activate(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    if not args.get("confirmed"):
        raise ShutongError("workspace_switch_needs_confirmation", "Confirm the project/work switch before changing the active workspace.")
    project = _read(_path(corpus_root, args["project_id"]))
    work_id = args["work_id"]
    if work_id not in {work["id"] for work in project["works"]}:
        raise ShutongError("work_not_in_project", "The requested work does not belong to this project.")
    papers.use({"paper_id": work_id, "confirmed": True}, corpus_root)
    workspace = {"project_id": project["id"], "work_id": work_id}
    path = papers.project_root(corpus_root) / ".shutong" / "active-workspace.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(workspace, indent=2) + "\n", encoding="utf-8")
    return {"status": "ok", "active": workspace}


def plan_switch(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    """Recommend, but never perform, a workspace transition from local metadata only."""
    query = args.get("query", "").strip()
    if not query:
        raise ShutongError("empty_workspace_query", "Workspace planning requires the scholar's new question or request.")
    query_words = set(re.findall(r"\w+", query.casefold()))
    candidates = []
    for project in list_workspaces({}, corpus_root)["projects"]:
        for work in project["works"]:
            haystack = " ".join((project["id"], project["title"], project.get("question", ""), work["id"], work["title"], work.get("question", ""))).casefold()
            score = len(query_words & set(re.findall(r"\w+", haystack)))
            if work["id"] in query.casefold() or project["id"] in query.casefold():
                score += 100
            if score:
                candidates.append({"project_id": project["id"], "project_title": project["title"], "work_id": work["id"], "work_title": work["title"], "score": score})
    candidates.sort(key=lambda item: (-item["score"], item["project_id"], item["work_id"]))
    current = active(corpus_root)
    recommended = candidates[0] if candidates else None
    action = "continue" if recommended and current and recommended["project_id"] == current["project_id"] and recommended["work_id"] == current["work_id"] else "confirm_switch" if recommended else "create_project_or_work"
    return {"status": "needs_scholar_confirmation", "query": query, "active": current, "action": action, "recommended": recommended, "candidates": candidates[:5], "message": "This planner never changes the active workspace; ask the scholar to confirm the recommended action."}
