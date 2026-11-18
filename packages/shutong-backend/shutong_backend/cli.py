"""Shutong 書童 CLI — Academic research layer."""

from __future__ import annotations

import json
import os
from pathlib import Path

import click

from . import doctor, templates
from .translation.glossary import add_entry, copy_file, list_all, lookup


def _shutong_config_dir() -> Path:
    xdg_root = os.environ.get("XDG_CONFIG_HOME")
    if xdg_root:
        return Path(xdg_root) / "shutong"
    return Path.home() / ".config" / "shutong"


def _write_file(path: Path, content: str, dry_run: bool) -> None:
    if dry_run:
        click.echo(f"[DRY-RUN] {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    click.echo(f"[OK] {path}")


def _ensure_directory(path: Path, dry_run: bool) -> None:
    if dry_run:
        click.echo(f"[DRY-RUN] {path}/")
        return
    path.mkdir(parents=True, exist_ok=True)
    click.echo(f"[OK] {path}/")


@click.group()
def cli():
    """Shutong 書童 — Academic research layer."""
    pass


@cli.command()
@click.option("--dry-run", is_flag=True, help="Print files without writing.")
def init(dry_run):
    """Initialize Shutong in the current project directory."""
    project_root = Path.cwd()
    click.echo("Shutong 書童 v0.4 — Academic Research Layer")
    click.echo()
    click.echo("Checking prerequisites...")
    doctor.run_checks(project_root)
    click.echo()
    click.echo("Creating project layer...")

    snapshot = templates.render_corpus_snapshot(project_root / "corpus")
    for relative_path, content in templates.project_files(snapshot).items():
        _write_file(project_root / relative_path, content, dry_run)
    _ensure_directory(project_root / "corpus", dry_run)
    _ensure_directory(project_root / "library", dry_run)


@cli.command()
def install():
    """Write global Scholar Principle to ~/.config/shutong/."""
    config_dir = _shutong_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "AGENTS.md").write_text(templates.render_global_agents_md(), encoding="utf-8")
    (config_dir / "shutong.json").write_text(
        json.dumps(templates.render_global_config(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    click.echo(f"[OK] {config_dir / 'AGENTS.md'}")
    click.echo(f"[OK] {config_dir / 'shutong.json'}")


@cli.command()
def sync():
    """Update AGENTS.md with current corpus document list."""
    project_root = Path.cwd()
    agents_path = project_root / "AGENTS.md"
    if not agents_path.exists():
        raise click.ClickException("AGENTS.md not found. Run `shutong init` first.")

    snapshot = templates.render_corpus_snapshot(project_root / "corpus")
    updated = templates.replace_corpus_snapshot(agents_path.read_text(encoding="utf-8"), snapshot)
    agents_path.write_text(updated, encoding="utf-8")
    click.echo(f"[OK] {agents_path}")


@cli.command()
@click.option("--surface", is_flag=True, help="Check the MCP and skill surface only.")
def doctor_cmd(surface):
    """Diagnose Shutong setup: Ollama, citeindex, GROBID, corpus."""
    if surface:
        failures = doctor.run_surface_checks(Path.cwd())
    else:
        failures = doctor.run_checks(Path.cwd())
    raise SystemExit(1 if failures else 0)


# Register 'doctor' as a command name (can't use @cli.command(name="doctor") easily)
cli.add_command(doctor_cmd, name="doctor")


@cli.group()
def glossary():
    """Manage translation glossaries."""
    pass


@glossary.command("add")
@click.argument("term_en")
@click.argument("term_zh")
@click.option("--file", default=None, help="Target glossary filename")
def glossary_add(term_en, term_zh, file):
    """Add EN→ZH glossary entry."""
    result = add_entry(term_en, term_zh, Path.cwd() / ".shutong" / "glossary", file=file)
    click.echo(json.dumps(result, indent=2, ensure_ascii=False))


@glossary.command("list")
def glossary_list():
    """List all glossary entries."""
    result = list_all(Path.cwd() / ".shutong" / "glossary")
    click.echo(json.dumps(result, indent=2, ensure_ascii=False))


@glossary.command("lookup")
@click.argument("term", nargs=-1, required=True)
def glossary_lookup(term):
    """Look up terms in glossaries."""
    result = lookup(list(term), Path.cwd() / ".shutong" / "glossary")
    click.echo(json.dumps(result, indent=2, ensure_ascii=False))


@glossary.command("load")
@click.argument("filepath")
def glossary_load(filepath):
    """Load an additional glossary JSON file."""
    result = copy_file(filepath, Path.cwd() / ".shutong" / "glossary")
    click.echo(json.dumps(result, indent=2, ensure_ascii=False))


def main() -> None:
    cli()


if __name__ == "__main__":
    main()