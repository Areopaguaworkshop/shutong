from __future__ import annotations

import json

import pytest

from shutong_backend.agents.pipeline import AcademicPipeline


@pytest.fixture
def no_llm(monkeypatch):
    """Force the LLM subprocess calls to fail fast, exercising deterministic fallbacks."""
    def _fail(*args, **kwargs):
        raise FileNotFoundError("ollama not available in tests")

    for mod in (
        "shutong_backend.agents.writing.outline.subprocess.run",
        "shutong_backend.agents.writing.draft.subprocess.run",
        "shutong_backend.agents.devils_advocate.subprocess.run",
    ):
        monkeypatch.setattr(mod, _fail)


def _make_corpus(tmp_path, source_id="src", text="Nicene theology and the Trinity"):
    corpus = tmp_path / "corpus"
    doc = corpus / source_id
    doc.mkdir(parents=True)
    (doc / "csl.json").write_text(
        json.dumps({"id": source_id, "title": "Test Source", "author": [{"family": "Doe", "given": "Jane"}], "issued": {"date-parts": [[2020]]}}),
        encoding="utf-8",
    )
    (doc / "document.json").write_text(
        json.dumps({"nodes": [{"node_id": f"{source_id}:1", "source_id": source_id, "text": text, "sha256": "a" * 64, "section_path": "p1"}]}),
        encoding="utf-8",
    )
    return str(corpus)


def test_research_mode_returns_evidence(tmp_path):
    corpus = _make_corpus(tmp_path)
    pipeline = AcademicPipeline(corpus_root=corpus, storage_dir=str(tmp_path / "state"))
    result = pipeline.run(topic="Nicene theology", mode="research", skip_checkpoints=True)
    assert result["status"] == "ok"
    assert result["evidence"], "research mode should return evidence"


def test_full_mode_runs_all_stages(tmp_path, no_llm):
    corpus = _make_corpus(tmp_path)
    pipeline = AcademicPipeline(corpus_root=corpus, storage_dir=str(tmp_path / "state"))
    result = pipeline.run(topic="Nicene theology", mode="full", skip_checkpoints=True)
    assert result["status"] == "ok"
    assert result["outline"], "outline should be generated"
    assert result["draft"], "draft should be generated"
    assert result["style_report"], "style report should be generated"
    assert result["quality_report"], "quality report should be generated"
    assert result["review"], "review should be generated"


def test_checkpoint_pauses_and_resumes(tmp_path, no_llm):
    corpus = _make_corpus(tmp_path)
    pipeline = AcademicPipeline(corpus_root=corpus, storage_dir=str(tmp_path / "state"))
    result = pipeline.run(topic="Nicene theology", mode="full", skip_checkpoints=False)
    assert result["status"] == "needs_checkpoint"
    assert result["stage"] == "research"
    pipeline_id = result["checkpoint"]["pipeline_id"]

    resumed = pipeline.resume(pipeline_id=pipeline_id, user_choice="proceed")
    # After research, next checkpoint is outline
    assert resumed["status"] == "needs_checkpoint"
    assert resumed["stage"] == "outline"


def test_resume_abort(tmp_path):
    corpus = _make_corpus(tmp_path)
    pipeline = AcademicPipeline(corpus_root=corpus, storage_dir=str(tmp_path / "state"))
    result = pipeline.run(topic="Nicene theology", mode="full", skip_checkpoints=False)
    pipeline_id = result["checkpoint"]["pipeline_id"]
    aborted = pipeline.resume(pipeline_id=pipeline_id, user_choice="abort")
    assert aborted["status"] == "aborted"


def test_resume_unknown_pipeline(tmp_path):
    pipeline = AcademicPipeline(corpus_root=str(tmp_path / "corpus"), storage_dir=str(tmp_path / "state"))
    result = pipeline.resume(pipeline_id="nonexistent", user_choice="proceed")
    assert result["status"] == "error"
