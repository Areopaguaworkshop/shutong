"""Shutong template rendering — Jinja2-backed config and scaffold generation."""

from __future__ import annotations

import json
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_TEMPLATE_DIR = Path(__file__).parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)

DEFAULT_GLOSSARY = json.loads(
    (_TEMPLATE_DIR / "glossary" / "theology-en-zh.json").read_text(encoding="utf-8")
)

CORPUS_BEGIN = "<!-- SHUTONG:CORPUS:BEGIN -->"
CORPUS_END = "<!-- SHUTONG:CORPUS:END -->"


def render_corpus_snapshot(corpus_root: Path) -> str:
    docs = sorted(path for path in corpus_root.iterdir() if path.is_dir()) if corpus_root.exists() else []
    if not docs:
        return "No documents ingested yet."

    lines = [f"- {doc.name}" for doc in docs[:25]]
    if len(docs) > 25:
        lines.append(f"- ... and {len(docs) - 25} more")
    return "\n".join(lines)


def replace_corpus_snapshot(content: str, snapshot: str) -> str:
    pattern = re.compile(
        rf"{re.escape(CORPUS_BEGIN)}.*?{re.escape(CORPUS_END)}",
        flags=re.DOTALL,
    )
    replacement = f"{CORPUS_BEGIN}\n{snapshot}\n{CORPUS_END}"
    if pattern.search(content):
        return pattern.sub(replacement, content)
    return f"{content.rstrip()}\n\n## Corpus Snapshot\n\n{replacement}\n"


def render_project_agents_md(snapshot: str) -> str:
    return _env.get_template("AGENTS.md.j2").render(snapshot=snapshot)


def render_global_agents_md() -> str:
    return (_TEMPLATE_DIR / "global-agents.md").read_text(encoding="utf-8")


def render_global_config() -> dict:
    return json.loads((_TEMPLATE_DIR / "global-shutong.json").read_text(encoding="utf-8"))


# Canonical role skills. The host agent loads one of these instead of delegating
# to an agent definition; there is no per-role agent layer.
ROLE_SKILLS = (
    "explore-bibliography",
    "ingest-source",
    "noter",
    "verify-bibliography",
    "workspace-planner",
    "paper-workspace",
)

# Supporting skills kept from the previous package surface, plus the routing
# skills (copyright-access) and the pipeline guide that replaces the removed
# ``shutong_pipeline`` tool contract.
_SUPPORT_SKILLS = (
    "academic-pipeline",
    "analysis-plan",
    "citation-check",
    "cite-research",
    "copyright-access",
    "corpus-status",
    "evidence-synthesis",
    "shutong-research",
    "text-analysis",
    "translate-academic",
    "verify-corpus",
)
PROJECT_SKILLS = (*ROLE_SKILLS, *_SUPPORT_SKILLS)

# Static file mapping: relative path within project → template file path.
#
# The wheel ships only ``shutong_backend/**``, so these role skills are copied
# from the repository's ``.agents/skills`` tree into package templates. Keep the
# two copies in sync; a single generated source is a follow-up.
_SKILL_FILES = {
    Path(f".agents/skills/{skill}/SKILL.md"): f"skills/{skill}/SKILL.md"
    for skill in PROJECT_SKILLS
}

_COMMAND_FILES = {
    Path(".shutong/commands/research.md"): "commands/research.md",
    Path(".shutong/commands/ingest.md"): "commands/ingest.md",
    Path(".shutong/commands/verify.md"): "commands/verify.md",
}


def project_files(snapshot: str) -> dict[Path, str]:
    """Return the project-layer files for ``shutong-backend init``.

    Deliberately no ``shutong.json``: Shutong does not own the host's config.
    Skills live in the universal ``.agents/skills`` root.
    """
    files: dict[Path, str] = {
        Path("AGENTS.md"): render_project_agents_md(snapshot),
    }

    for dest_path, src_name in {**_SKILL_FILES, **_COMMAND_FILES}.items():
        src_path = _TEMPLATE_DIR / src_name
        files[dest_path] = src_path.read_text(encoding="utf-8")

    return files
