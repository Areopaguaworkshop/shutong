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


def render_project_config() -> dict:
    return json.loads((_TEMPLATE_DIR / "shutong.json").read_text(encoding="utf-8"))


def render_global_config() -> dict:
    return json.loads((_TEMPLATE_DIR / "global-shutong.json").read_text(encoding="utf-8"))


# Static file mapping: relative path within project → template file path
# Agent definitions are no longer written: skills carry the role prompts.
_SKILL_FILES = {
    Path(".shutong/skills/cite-research/SKILL.md"): "skills/cite-research/SKILL.md",
    Path(".shutong/skills/ingest-source/SKILL.md"): "skills/ingest-source/SKILL.md",
    Path(".shutong/skills/verify-corpus/SKILL.md"): "skills/verify-corpus/SKILL.md",
    Path(".shutong/skills/workspace-planner/SKILL.md"): "skills/workspace-planner/SKILL.md",
}
for _skill in ("analysis-plan", "text-analysis", "evidence-synthesis", "citation-check", "translate-academic"):
    _SKILL_FILES[Path(f".shutong/skills/{_skill}/SKILL.md")] = f"skills/{_skill}/SKILL.md"

_COMMAND_FILES = {
    Path(".shutong/commands/research.md"): "commands/research.md",
    Path(".shutong/commands/ingest.md"): "commands/ingest.md",
    Path(".shutong/commands/verify.md"): "commands/verify.md",
}


def project_files(snapshot: str) -> dict[Path, str]:
    files: dict[Path, str] = {
        Path("AGENTS.md"): render_project_agents_md(snapshot),
        Path("shutong.json"): json.dumps(render_project_config(), indent=2, ensure_ascii=False) + "\n",
    }

    for dest_path, src_name in {**_SKILL_FILES, **_COMMAND_FILES}.items():
        src_path = _TEMPLATE_DIR / src_name
        files[dest_path] = src_path.read_text(encoding="utf-8")

    return files
