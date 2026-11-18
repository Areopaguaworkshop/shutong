"""Shutong doctor — diagnostic checks for the scholar research layer."""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import os
import shutil
from pathlib import Path

import requests


def _check_command(*names: str) -> tuple[bool, str]:
    for name in names:
        path = shutil.which(name)
        if path:
            return True, path
    return False, "not found"


def _ollama_base_url() -> str:
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    return base_url.rstrip("/")


def _get_citeindex_version() -> str:
    try:
        return importlib.metadata.version("citeindex")
    except Exception:
        return "not installed"


def collect_checks(project_root: Path | None = None) -> list[dict[str, str | bool]]:
    root = project_root or Path.cwd()
    checks: list[dict[str, str | bool]] = []

    backend_ok, backend_detail = _check_command("shutong-backend", "shutong-backend-mcp")
    checks.append({"name": "shutong", "ok": backend_ok, "detail": backend_detail})

    # citeindex package + version
    citeindex_ok = importlib.util.find_spec("citeindex") is not None
    citeindex_ver = _get_citeindex_version() if citeindex_ok else "missing"
    checks.append({"name": "citeindex", "ok": citeindex_ok, "detail": f"v{citeindex_ver}" if citeindex_ok else "missing"})

    backend_pkg_ok = importlib.util.find_spec("shutong_backend") is not None
    checks.append({"name": "shutong_backend", "ok": backend_pkg_ok, "detail": "importable" if backend_pkg_ok else "missing"})

    # Ollama server
    ollama_url = _ollama_base_url()
    try:
        response = requests.get(f"{ollama_url}/api/tags", timeout=5)
        response.raise_for_status()
        models = [model.get("name", "") for model in response.json().get("models", [])]
        checks.append({"name": "Ollama", "ok": True, "detail": ollama_url})

        glm_ok = any("glm-5.3-flash" in name and "cloud" in name for name in models)
        glm_match = [n for n in models if "glm-5.3-flash" in n]
        checks.append({
            "name": "Ollama glm-5.3-flash:cloud",
            "ok": glm_ok,
            "detail": glm_match[0] if glm_match else "not pulled",
        })

        # Check qwen3:4b
        qwen3_4b_ok = any("qwen3" in name and "4b" in name for name in models)
        qwen3_4b_match = [n for n in models if "qwen3" in n and "4b" in n]
        checks.append({
            "name": "Ollama qwen3:4b",
            "ok": qwen3_4b_ok,
            "detail": qwen3_4b_match[0] if qwen3_4b_match else "not pulled",
        })
    except Exception as exc:  # pragma: no cover - network-dependent
        checks.append({"name": "Ollama", "ok": False, "detail": str(exc)})

    # GROBID
    try:
        response = requests.get("http://localhost:8070/api/isalive", timeout=3)
        checks.append({"name": "GROBID", "ok": response.ok, "detail": "running" if response.ok else f"HTTP {response.status_code}"})
    except Exception as exc:  # pragma: no cover - network-dependent
        checks.append({"name": "GROBID", "ok": False, "detail": str(exc)})

    # Corpus and library directories
    corpus_root = root / "corpus"
    library_root = root / "library"
    checks.append({"name": "Corpus directory", "ok": corpus_root.exists(), "detail": str(corpus_root)})
    checks.append({"name": "Library directory", "ok": library_root.exists(), "detail": str(library_root)})

    return checks


def run_checks(project_root: Path | None = None) -> int:
    """Run all diagnostic checks. Returns number of failures."""
    failures = 0
    for check in collect_checks(project_root):
        ok = bool(check["ok"])
        status = "OK" if ok else "FAIL"
        print(f"[{status}] {check['name']}: {check['detail']}")
        if not ok:
            failures += 1
    return failures


# --- Surface checks: MCP plus skills, no agent layer -------------------------

_ROLE_SKILLS = (
    "explore-bibliography",
    "ingest-source",
    "noter",
    "verify-bibliography",
    "workspace-planner",
    "paper-workspace",
)

_SKILL_ROOTS = (".agents/skills", ".claude/skills", ".codex/skills", ".pi/skills", ".shutong/skills")

_AGENT_DIRS = (".opencode/agents", ".claude/agents", ".codex/agents", ".shutong/agents")


def collect_surface_checks(project_root: Path | None = None) -> list[dict[str, str | bool]]:
    """Check the shipped surface: MCP tools, skill pack, no agent layer."""
    root = project_root or Path.cwd()
    checks: list[dict[str, str | bool]] = []

    try:
        from shutong_backend import mcp_server

        names = [tool["name"] for tool in mcp_server.TOOL_DEFINITIONS]
        checks.append({
            "name": "MCP surface",
            "ok": len(names) >= 26,
            "detail": f"{len(names)} tools",
        })
    except Exception as exc:  # pragma: no cover - import-dependent
        checks.append({"name": "MCP surface", "ok": False, "detail": str(exc)})

    present = {
        skill
        for skill_root in _SKILL_ROOTS
        for skill in _ROLE_SKILLS
        if (root / skill_root / skill / "SKILL.md").is_file()
    }
    missing = sorted(set(_ROLE_SKILLS) - present)
    checks.append({
        "name": "Skill pack",
        "ok": not missing,
        "detail": "role skills present" if not missing else f"missing {', '.join(missing)}",
    })

    agent_dirs = [name for name in _AGENT_DIRS if (root / name).exists()]
    checks.append({
        "name": "No agent layer",
        "ok": not agent_dirs,
        "detail": "none" if not agent_dirs else f"unexpected {', '.join(agent_dirs)}",
    })

    agents_md = root / "AGENTS.md"
    routes_by_skill = False
    if agents_md.is_file():
        routes_by_skill = "Route by skill" in agents_md.read_text(encoding="utf-8", errors="replace")
    checks.append({
        "name": "AGENTS.md skill routing",
        "ok": routes_by_skill,
        "detail": str(agents_md) if routes_by_skill else "missing routing section",
    })

    return checks


def run_surface_checks(project_root: Path | None = None) -> int:
    """Run surface checks. Returns number of failures."""
    failures = 0
    for check in collect_surface_checks(project_root):
        ok = bool(check["ok"])
        print(f"[{'OK' if ok else 'FAIL'}] {check['name']}: {check['detail']}")
        if not ok:
            failures += 1
    return failures
