"""Integration tests — verify the full Shutong pipeline works end-to-end."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    """Create a minimal project tree for integration testing."""
    # Create corpus with a test document
    corpus = tmp_path / "corpus" / "Smith_2025_Logos"
    corpus.mkdir(parents=True)
    (corpus / "document.json").write_text(
        json.dumps({
            "csl_id": "Smith_2025_Logos",
            "title": "The Logos in Patristic Thought",
            "author": [{"family": "Smith", "given": "John"}],
            "issued": {"date-parts": [[2025]]},
            "type": "article",
        }),
        encoding="utf-8",
    )

    # Create a page index tree with content
    (corpus / "pageindex_tree.json").write_text(
        json.dumps({
            "children": [
                {
                    "text": "Introduction",
                    "type": "heading",
                    "children": [
                        {
                            "text": "The concept of logos (Smith 2025, 42) is central to patristic theology. "
                            "Hypostasis and ousia are technical terms that require precise translation.",
                            "type": "paragraph",
                        },
                    ],
                }
            ]
        }),
        encoding="utf-8",
    )

    # Create glossary
    glossary = tmp_path / ".shutong" / "glossary"
    glossary.mkdir(parents=True)
    (glossary / "theology-en-zh.json").write_text(
        json.dumps({"logos": "道", "hypostasis": "位格", "ousia": "本质"}),
        encoding="utf-8",
    )

    # Create library
    library = tmp_path / "library"
    library.mkdir(parents=True)

    return tmp_path


@pytest.fixture()
def env_setup(project_root: Path, monkeypatch):
    """Set environment variables for Shutong tools."""
    monkeypatch.setenv("SHUTONG_CORPUS_ROOT", str(project_root / "corpus"))
    monkeypatch.setenv("SHUTONG_LIBRARY_ROOT", str(project_root / "library"))
    monkeypatch.setenv("SHUTONG_GLOSSARY_DIR", str(project_root / ".shutong" / "glossary"))


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestProjectInit:
    """Test shutong init creates the no-agent, skill-routed project surface."""

    def test_init_creates_agents_md_with_skill_routing(self):
        from shutong_backend.templates import render_project_agents_md

        agents_md = render_project_agents_md("Smith_2025_Logos")
        assert "Scholar Principle" in agents_md
        assert "Smith_2025_Logos" in agents_md
        assert "Shutong ships no agent definitions" in agents_md
        assert "Route by skill, not by subagent" in agents_md
        assert "`explore-bibliography`" in agents_md
        assert "`verify-bibliography`" in agents_md

    def test_init_writes_no_agent_layer_and_no_host_config(self):
        from shutong_backend.templates import PROJECT_SKILLS, ROLE_SKILLS, project_files

        files = project_files("test snapshot")
        paths = {str(path) for path in files}

        assert "AGENTS.md" in paths
        assert not any(path.startswith(".shutong/agents/") for path in paths)
        assert not any(path.startswith(".shutong/skills/") for path in paths)
        assert "shutong.json" not in paths
        assert not any(path.endswith("/shutong.json") for path in paths)
        assert "default_agent" not in "\n".join(files.values())
        assert len(PROJECT_SKILLS) == 17
        for skill in PROJECT_SKILLS:
            assert f".agents/skills/{skill}/SKILL.md" in paths

        for skill in ROLE_SKILLS:
            assert f".agents/skills/{skill}/SKILL.md" in paths

        for command in ("research", "ingest", "verify"):
            assert f".shutong/commands/{command}.md" in paths
            assert "agent:" not in files[Path(f".shutong/commands/{command}.md")]

    def test_role_skills_carry_current_tool_contracts(self):
        from shutong_backend.templates import ROLE_SKILLS, project_files

        files = project_files("test snapshot")
        expected = {
            "explore-bibliography": "shutong_bibliography_search",
            "ingest-source": "mark_ingested",
            "noter": "shutong_note",
            "verify-bibliography": "shutong_verifier_report",
            "workspace-planner": "plan_switch",
            "paper-workspace": "shutong_workspace",
        }
        assert set(expected) == set(ROLE_SKILLS)

        skill_text = "\n".join(
            files[Path(f".agents/skills/{skill}/SKILL.md")] for skill in ROLE_SKILLS
        )
        for skill, token in expected.items():
            assert token in files[Path(f".agents/skills/{skill}/SKILL.md")], skill
        assert "shutong_pipeline" not in skill_text
        assert "shutong_glossary_add" not in skill_text
        assert "action `all`" not in skill_text
        assert "mode: all" in files[Path(".agents/skills/verify-corpus/SKILL.md")]


class TestIngestionStatus:
    def test_ingest_uses_configured_llm(self, monkeypatch):
        from shutong_backend.tools.ingest import _llm_model

        monkeypatch.setenv("SHUTONG_LLM_PROVIDER", "ollama")
        monkeypatch.setenv("SHUTONG_LLM_MODEL", "glm-5.3-flash:cloud")
        assert _llm_model() == "ollama/glm-5.3-flash:cloud"

    def test_existing_ingestion_is_recovered(self, project_root: Path):
        from shutong_backend.tools.ingest import _existing_ingestion

        source = project_root / "King.pdf"
        source.write_text("source", encoding="utf-8")
        document = project_root / "corpus" / "king" 
        document.mkdir()
        (document / "ingestion_output.json").write_text(json.dumps({
            "standardized_csl_json": {"id": "king", "merkle_root": "abc", "type": "book"},
            "sub_pipeline_outputs": {"document_json": {"metadata": {"source_path": str(source)}, "nodes": [{"node_id": "1"}]}},
        }), encoding="utf-8")

        assert _existing_ingestion(str(source), str(project_root / "corpus"))["csl_id"] == "king"

    @pytest.mark.asyncio
    async def test_ingest_status_reads_persisted_result(self, project_root: Path):
        from shutong_backend.tools.ingest import ingest_status

        status_path = project_root / ".shutong" / "ingestion-status.json"
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(json.dumps({"status": "running", "source": "source.pdf"}), encoding="utf-8")

        assert await ingest_status({}, str(project_root / "corpus")) == {"status": "running", "source": "source.pdf"}


class TestGlossaryIntegration:
    """Test glossary lookup works end-to-end with real file I/O."""

    @pytest.mark.asyncio
    async def test_glossary_add_lookup_roundtrip(self, project_root: Path, env_setup):
        from shutong_backend.translation.glossary import add_entry, lookup
        from shutong_backend.mcp_server import get_glossary_dir

        glossary_dir = Path(get_glossary_dir())

        # Add a term
        result = add_entry("perichoresis", "互契", glossary_dir)
        assert result["status"] == "ok"

        # Look it up — returns dict with zh and source_file
        matches = lookup(["perichoresis"], glossary_dir)
        assert "perichoresis" in matches
        assert matches["perichoresis"]["zh"] == "互契"

    @pytest.mark.asyncio
    async def test_glossary_reads_default_terms(self, project_root: Path, env_setup):
        from shutong_backend.translation.glossary import lookup
        from shutong_backend.mcp_server import get_glossary_dir

        glossary_dir = Path(get_glossary_dir())
        matches = lookup(["logos", "hypostasis"], glossary_dir)
        assert matches["logos"]["zh"] == "道"
        assert matches["hypostasis"]["zh"] == "位格"


class TestTranslationPipelineIntegration:
    """Test the translation pipeline resolves sources and builds prompts."""

    @pytest.mark.asyncio
    async def test_resolve_source_corpus(self, project_root: Path, env_setup):
        from shutong_backend.translation.pipeline import resolve_source
        from shutong_backend.mcp_server import get_corpus_root

        result = resolve_source("Smith_2025_Logos", corpus_root=get_corpus_root())
        assert result["source_type"] == "corpus"
        # CorpusLoader may return source_id or csl_id depending on the loader
        assert "source_id" in result or "csl_id" in result

    @pytest.mark.asyncio
    async def test_resolve_source_text(self, project_root: Path, env_setup):
        from shutong_backend.translation.pipeline import resolve_source
        from shutong_backend.mcp_server import get_corpus_root

        result = resolve_source("The quick brown fox", corpus_root=get_corpus_root())
        assert result["source_type"] == "text"

    @pytest.mark.asyncio
    async def test_build_system_prompt_with_glossary(self, project_root: Path, env_setup):
        from shutong_backend.translation.pipeline import build_system_prompt

        glossary = {"logos": "道", "hypostasis": "位格"}
        prompt = build_system_prompt(glossary)
        assert "道" in prompt
        assert "位格" in prompt
        assert "Mandatory" in prompt

    @pytest.mark.asyncio
    async def test_flag_untranslated(self, project_root: Path, env_setup):
        from shutong_backend.translation.pipeline import flag_untranslated

        zh_text = "这位格的概念很重要，但 [未译: Apophatic] 神学也很关键。"
        en_text = "The concept of hypostasis is important, but Apophatic theology is also key."
        glossary = {"hypostasis": "位格"}
        result = flag_untranslated(zh_text, en_text, glossary)
        assert "Apophatic" in result


class TestDoctorIntegration:
    """Test doctor checks against a project root."""

    def test_doctor_collects_checks(self, project_root: Path, env_setup):
        from shutong_backend.doctor import collect_checks

        checks = collect_checks(project_root)
        names = {c["name"] for c in checks}
        assert "citeindex" in names
        assert "shutong" in names
        assert "Ollama" in names
        assert "Corpus directory" in names

    def test_doctor_corpus_exists(self, project_root: Path, env_setup):
        from shutong_backend.doctor import collect_checks

        checks = collect_checks(project_root)
        corpus_check = next(c for c in checks if c["name"] == "Corpus directory")
        assert corpus_check["ok"] is True


class TestDoctorSurface:
    """Test doctor --surface against the init output and host skill paths."""

    @staticmethod
    def _write_init_files(root: Path) -> None:
        from shutong_backend.templates import project_files

        for relative_path, content in project_files("Smith_2025_Logos").items():
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def test_clean_init_passes_surface_checks(self, tmp_path: Path):
        from shutong_backend.doctor import collect_surface_checks

        self._write_init_files(tmp_path)
        checks = {check["name"]: check for check in collect_surface_checks(tmp_path)}

        assert checks["Packaged skill pack"]["ok"] is True
        assert checks["Project skill pack"]["ok"] is True
        assert checks["No agent layer"]["ok"] is True
        assert checks["AGENTS.md skill routing"]["ok"] is True

    def test_legacy_shutong_skills_do_not_satisfy_host_pack(self, tmp_path: Path):
        from shutong_backend.doctor import collect_surface_checks
        from shutong_backend.templates import ROLE_SKILLS

        for skill in ROLE_SKILLS:
            path = tmp_path / ".shutong" / "skills" / skill / "SKILL.md"
            path.parent.mkdir(parents=True)
            path.write_text(f"# {skill}\n", encoding="utf-8")

        checks = {check["name"]: check for check in collect_surface_checks(tmp_path)}
        assert checks["Project skill pack"]["ok"] is False
        assert ".shutong/skills" not in checks["Project skill pack"]["detail"]

    def test_partial_host_pack_is_reported_missing(self, tmp_path: Path):
        from shutong_backend.doctor import collect_surface_checks

        path = tmp_path / ".agents" / "skills" / "explore-bibliography" / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text("# explore-bibliography\n", encoding="utf-8")

        checks = {check["name"]: check for check in collect_surface_checks(tmp_path)}
        assert checks["Project skill pack"]["ok"] is False
        assert "ingest-source" in checks["Project skill pack"]["detail"]

    def test_incomplete_host_roots_are_not_combined(self, tmp_path: Path):
        from shutong_backend.doctor import collect_surface_checks

        for root_name, skill in (
            (".agents/skills", "explore-bibliography"),
            (".claude/skills", "ingest-source"),
        ):
            path = tmp_path / root_name / skill / "SKILL.md"
            path.parent.mkdir(parents=True)
            path.write_text(f"# {skill}\n", encoding="utf-8")

        checks = {check["name"]: check for check in collect_surface_checks(tmp_path)}
        assert checks["Project skill pack"]["ok"] is False
        assert ".agents/skills missing" in checks["Project skill pack"]["detail"]


class TestMCPServerIntegration:
    """Test MCP server dispatches tool calls correctly."""

    @pytest.mark.asyncio
    async def test_call_tool_unknown(self, project_root: Path, env_setup):
        from shutong_backend.mcp_server import call_tool

        result = await call_tool("shutong_nonexistent", {})
        payload = json.loads(result[0]["text"])
        assert payload["status"] == "error"
        assert payload["error_code"] == "unknown_tool"

    @pytest.mark.asyncio
    async def test_removed_glossary_tool_is_unknown(self, project_root: Path, env_setup):
        from shutong_backend.mcp_server import call_tool

        result = await call_tool("shutong_glossary_add", {
            "term_en": "theosis",
            "term_zh": "神化",
        })
        payload = json.loads(result[0]["text"])
        assert payload["status"] == "error"
        assert payload["error_code"] == "unknown_tool"

    @pytest.mark.asyncio
    async def test_grouped_workspace_tool_dispatches(self, project_root: Path, env_setup):
        from shutong_backend.mcp_server import call_tool

        result = await call_tool("shutong_workspace", {"action": "list"})
        payload = json.loads(result[0]["text"])
        assert payload["status"] == "ok"
        assert "projects" in payload

    @pytest.mark.asyncio
    async def test_call_tool_corpus_status(self, project_root: Path, env_setup):
        from shutong_backend.mcp_server import call_tool

        result = await call_tool("shutong_corpus_status", {})
        payload = json.loads(result[0]["text"])
        # Returns ok or error depending on corpus state — either is valid
        assert "status" in payload


class TestCLIIntegration:
    """Test CLI commands work."""

    def test_cli_help(self):
        from click.testing import CliRunner
        from shutong_backend.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Shutong" in result.output

    def test_cli_glossary_help(self):
        from click.testing import CliRunner
        from shutong_backend.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["glossary", "--help"])
        assert result.exit_code == 0
        assert "add" in result.output

    def test_cli_init_dry_run(self, project_root: Path, env_setup):
        from click.testing import CliRunner
        from shutong_backend.cli import cli

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=str(project_root)):
            result = runner.invoke(cli, ["init", "--dry-run"])
            assert result.exit_code == 0
            assert "DRY-RUN" in result.output

    def test_cli_init_writes_universal_skill_root(self, tmp_path: Path, monkeypatch):
        from click.testing import CliRunner

        import shutong_backend.cli as cli_module
        from shutong_backend.cli import cli

        monkeypatch.setattr(cli_module.doctor, "run_checks", lambda *_args, **_kwargs: 0)
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=str(tmp_path)):
            result = runner.invoke(cli, ["init"])
            assert result.exit_code == 0

            assert Path(".agents/skills/explore-bibliography/SKILL.md").is_file()
            assert Path(".agents/skills/noter/SKILL.md").is_file()
            assert Path(".agents/skills/verify-bibliography/SKILL.md").is_file()
            assert not Path("shutong.json").exists()
            assert not Path(".shutong/agents").exists()
            assert not Path(".shutong/skills").exists()
            assert "Route by skill" in Path("AGENTS.md").read_text(encoding="utf-8")
