from __future__ import annotations

import json

import pytest
from citeindex.ingestion.deterministic import build_merkle_tree, hash_payload

from shutong_backend import analysis, papers
from shutong_backend.mcp_server import call_tool, TOOL_DEFINITIONS
from shutong_backend.tools.errors import ShutongError


def source(corpus, source_id, text):
    directory = corpus / source_id
    directory.mkdir(parents=True, exist_ok=True)
    node = {"node_id": f"{source_id}:p1:n1", "text": text, "sha256": hash_payload(text), "page": 1}
    for name, data in {"csl": {"id": source_id, "title": source_id, "author": [{"family": "Example"}], "issued": {"date-parts": [[2020]]}},
                       "document": {"nodes": [node]}, "merkle": build_merkle_tree([node["sha256"]])}.items():
        (directory / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "corpus"
    source(root, "a", "Bright hope guides us. Hope brings peace.")
    source(root, "b", "Bright hope guides us. A grave warning follows.")
    source(root, "zh", "慈爱带来盼望。盼望胜过恐惧。")
    source(root, "outside", "PRIVATE unrelated hope")
    papers.create({"paper_id": "study", "title": "Synthetic", "minimum_primary": 0, "minimum_secondary": 0}, str(root))
    papers.set_bibliography({"paper_id": "study", "entries": [{"id": s} for s in ("a", "b", "zh")]}, str(root))
    papers.approve_bibliography({"paper_id": "study"}, str(root))
    for s in ("a", "b", "zh"):
        papers.add_source({"paper_id": "study", "source_id": s, "role": "primary"}, str(root))
        papers.set_source_access({"paper_id": "study", "source_id": s, "category": "open"}, str(root))
    papers.authorize_ingestion({"paper_id": "study", "mode": "automatic", "rule": "test fixture"}, str(root))
    registry_path = tmp_path / ".shutong" / "source-registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps({
        source_id: {
            "document_path": str(root / source_id),
            "merkle_root": json.loads((root / source_id / "merkle.json").read_text())["root"],
        }
        for source_id in ("a", "b", "zh")
    }), encoding="utf-8")
    for source_id in ("a", "b", "zh"):
        papers.mark_source_ingested({"paper_id": "study", "source_id": source_id}, str(root))
    return root


def run(corpus, mode="concordance", **kwargs):
    return analysis.dispatch({"action": "run", "paper_id": "study", "mode": mode, "language": "en", "question": "How is hope used?", "source_ids": ["a"], "query": "hope", **kwargs}, str(corpus))


def ref(response):
    return {"paper_id": "study", "analysis_id": response["analysis"]["analysis_id"], "record_sha256": response["record_sha256"]}


def review(corpus, response, outcome="pass"):
    return analysis.dispatch({"action": "review", **ref(response), "outcome": outcome, "reviewer": "synthetic-verifier", "evidence": "Checked source spans and exact counts."}, str(corpus))


def test_concordance_collocations_and_original_offsets(corpus):
    response = run(corpus, limit=1)
    record = response["analysis"]
    assert record["results"]["total_occurrences"] == 2
    assert record["results"]["truncated"] is True
    hit = record["results"]["contexts"][0]
    assert hit["text"] == "hope" and hit["start"] == 7 and hit["end"] == 11
    assert hit["source_id"] == "a" and hit["page"] == 1
    assert record["review"]["outcome"] == "pending"
    saved = analysis.get(ref(response), str(corpus))
    assert saved == response
    result = run(corpus, "collocations", window=1)["analysis"]["results"]
    assert result["target_occurrences"] == 2 and result["corpus_tokens"] == 7
    assert {row["token"]: row["count"] for row in result["collocates"]} == {"bright": 1, "guides": 1, "us": 1, "brings": 1}
    assert all(row["document_frequency"] == 1 for row in result["collocates"])


def test_chinese_character_units_and_exact_quotes(corpus):
    result = run(corpus, language="zh", source_ids=["zh"], query="盼望")["analysis"]["results"]
    assert result["total_occurrences"] == 2
    assert [(c["start"], c["end"], c["text"]) for c in result["contexts"]] == [(4, 6, "盼望"), (7, 9, "盼望")]
    assert analysis._tokens("cafe\u0301")[0] == ("café", 0, 5)
    exact = run(corpus, "quotation", query="Hope brings peace.")["analysis"]["results"]
    assert exact["total_occurrences"] == 1 and exact["contexts"][0]["text"] == "Hope brings peace."
    assert run(corpus, "quotation", query="hope brings peace.")["analysis"]["results"]["total_occurrences"] == 0


def test_reuse_compares_sources_not_notes(corpus):
    note = corpus.parent / "papers/study/notes/boilerplate.md"
    note.write_text("UNRELATED repeated private note boilerplate")
    result = run(corpus, "text_reuse", source_ids=["a", "b"], minimum_tokens=4)["analysis"]["results"]
    assert result["total_match_groups"] == 1
    group = result["matches"][0]
    assert group["tokens"] == ["bright", "hope", "guides", "us"]
    assert {x["source_id"] for x in group["occurrences"]} == {"a", "b"}
    assert all(x["text"] == "Bright hope guides us" for x in group["occurrences"])


@pytest.mark.parametrize("changes", [{"source_ids": ["outside"]}, {"source_ids": []}, {"source_ids": ["a", "a"]},
    {"paper_id": "../study"}, {"window": True}, {"limit": 201}, {"language": "unsupported"}, {"mode": "fuzzy"}, {"library_wide": True}])
def test_rejects_invalid_or_unscoped_requests(corpus, changes):
    with pytest.raises(ShutongError):
        run(corpus, **changes)


def test_integrity_staleness_and_source_approval(corpus):
    response = run(corpus)
    source(corpus, "a", "A changed but internally consistent corpus.")
    with pytest.raises(ShutongError, match="changed"):
        analysis.get(ref(response), str(corpus))
    path = corpus / "a/document.json"
    data = json.loads(path.read_text())
    data["nodes"][0]["text"] = "Tampered without rehashing"
    path.write_text(json.dumps(data))
    with pytest.raises(ShutongError, match="integrity failed"):
        run(corpus)
    papers.set_bibliography({"paper_id": "study", "entries": [{"id": "a"}]}, str(corpus))
    with pytest.raises(ShutongError, match="Approve"):
        run(corpus)


def test_sentiment_is_recorded_interpretation_with_review(corpus):
    response = run(corpus, "contextual_sentiment", rubric="Assess the narrator's stance toward hope; retain ambiguity.")
    assert response["analysis"]["annotations"] == []
    with pytest.raises(ShutongError, match="retrieval alone"):
        review(corpus, response)
    annotation = {"context_index": 0, "label": "uncertain", "target": "hope", "speaker": "narrator", "rationale": "Insufficient wider context", "confidence": "probable"}
    response = analysis.dispatch({"action": "annotate", **ref(response), "model_id": "test-model", "annotations": [annotation]}, str(corpus))
    assert response["analysis"]["annotations"][0]["label"] == "uncertain"
    assert response["analysis"]["interpretation"]["model_id"] == "test-model"
    assert review(corpus, response, "uncertain")["analysis"]["review"]["outcome"] == "uncertain"
    with pytest.raises(ShutongError, match="exact inspected"):
        review(corpus, response)


def test_analysis_note_claim_and_draft_gate(corpus):
    response = run(corpus, "collocations", window=1)
    note = {"paper_id": "study", "source_id": "a", "locator": "a:p1:n1", "analysis_id": response["analysis"]["analysis_id"],
            "claim": "Hope occurs twice in source A.", "evidence": "Run target_occurrences=2; inspected source spans.", "confidence": "known", "tags": ["analysis"]}
    papers.add_note(note, str(corpus))
    papers.record_verifier_report({
        "paper_id": "study", "report_id": "note-review-1", "scope": "note:note-1",
        "outcome": "pass", "evidence": "Checked the source span and reviewed analysis record.",
    }, str(corpus))
    with pytest.raises(ShutongError, match="passing analysis review"):
        papers.verify_note({"paper_id": "study", "note_id": "note-1", "evidence": "note-review-1"}, str(corpus))
    response = review(corpus, response)
    papers.verify_note({"paper_id": "study", "note_id": "note-1", "evidence": "note-review-1"}, str(corpus))
    papers.add_claim({"paper_id": "study", "text": note["claim"], "note_ids": ["note-1"]}, str(corpus))
    papers.record_verifier_report({
        "paper_id": "study", "report_id": "claim-review-1", "scope": "claim:claim-1",
        "outcome": "pass", "evidence": "Checked claim against note note-1.",
    }, str(corpus))
    papers.verify_claim({"paper_id": "study", "claim_id": "claim-1", "evidence": "claim-review-1"}, str(corpus))
    assert papers.draft_context({"paper_id": "study", "draft_requested": True}, str(corpus))["status"] == "ready"
    review(corpus, response, "fail")
    assert papers.draft_context({"paper_id": "study", "draft_requested": True}, str(corpus))["status"] == "needs_evidence"


@pytest.mark.asyncio
async def test_public_mcp_dispatch_and_schema(corpus, monkeypatch):
    monkeypatch.setenv("SHUTONG_CORPUS_ROOT", str(corpus))
    assert any(t["name"] == "shutong_analysis" for t in TOOL_DEFINITIONS)
    raw = await call_tool("shutong_analysis", {"action": "run", "paper_id": "study", "source_ids": ["a"], "mode": "quotation", "language": "en", "question": "Check this quote", "query": "Bright hope"})
    payload = json.loads(raw[0]["text"])
    assert payload["status"] == "ok" and payload["analysis"]["results"]["total_occurrences"] == 1
    raw = await call_tool("shutong_analysis", {"action": "run", "paper_id": "study"})
    assert json.loads(raw[0]["text"])["error_code"] == "invalid_input"
