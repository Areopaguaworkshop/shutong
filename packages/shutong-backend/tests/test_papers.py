from __future__ import annotations

import json
import zipfile

import pytest

from shutong_backend import papers
from shutong_backend import workspaces
from shutong_backend.tools import research
from shutong_backend.tools.errors import ShutongError


def _write_document(root, source_id):
    document = root / "corpus" / source_id
    document.mkdir(parents=True, exist_ok=True)
    (document / "document.json").write_text(
        json.dumps({"nodes": [{"node_id": f"{source_id}:1", "source_id": source_id, "text": f"{source_id} source"}]}),
        encoding="utf-8",
    )
    (document / "merkle.json").write_text(json.dumps({"root": f"root-{source_id}", "levels": [[f"leaf-{source_id}"]]}), encoding="utf-8")
    return document


def _write_registry(root, records):
    registry = root / ".shutong" / "source-registry.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(json.dumps(records), encoding="utf-8")
    return registry


def _ingest(root, source_ids):
    records = {}
    for source_id in source_ids:
        document = _write_document(root, source_id)
        records[source_id] = {"document_path": str(document), "merkle_root": f"root-{source_id}"}
    _write_registry(root, records)


def _make_paper(root, source_ids=("athanasius", "ayres"), *, ingest=True, minimum_primary=1, minimum_secondary=1):
    corpus = root / "corpus"
    corpus.mkdir(parents=True, exist_ok=True)
    papers.create({"paper_id": "nicea", "title": "Nicaea", "minimum_primary": minimum_primary, "minimum_secondary": minimum_secondary}, str(corpus))
    papers.set_bibliography({"paper_id": "nicea", "entries": [{"id": source_id} for source_id in source_ids]}, str(corpus))
    papers.approve_bibliography({"paper_id": "nicea"}, str(corpus))
    for index, source_id in enumerate(source_ids):
        papers.add_source({"paper_id": "nicea", "source_id": source_id, "role": "primary" if index == 0 else "secondary"}, str(corpus))
        papers.set_source_access({"paper_id": "nicea", "source_id": source_id, "category": "open", "provenance": "publisher OA page"}, str(corpus))
    papers.authorize_ingestion({"paper_id": "nicea", "mode": "automatic", "rule": "open sources only"}, str(corpus))
    if ingest:
        _ingest(root, source_ids)
        for source_id in source_ids:
            papers.mark_source_ingested({"paper_id": "nicea", "source_id": source_id}, str(corpus))
    return str(corpus)


def _add_note(corpus, *, source_id="athanasius", note_id=None, locator="athanasius:1", claim="Evidence", evidence="Source passage."):
    args = {"paper_id": "nicea", "source_id": source_id, "locator": locator, "claim": claim, "evidence": evidence, "confidence": "known", "tags": ["doctrine"]}
    if note_id:
        args["note_id"] = note_id
    return papers.add_note(args, corpus)


def _verify_note(corpus, note_id="note-1", *, report_id=None, evidence=None):
    if report_id is None and evidence is None:
        report_id = papers.record_verifier_report({"paper_id": "nicea", "outcome": "pass", "scope": f"note:{note_id}"}, corpus)["report_id"]
    args = {"paper_id": "nicea", "note_id": note_id, "evidence": evidence or report_id or "audit:1"}
    if report_id:
        args["report_id"] = report_id
    return papers.verify_note(args, corpus)


def _add_claim(corpus, *, claim_id=None, note_ids=("note-1",), text="Evidence supports the paper."):
    args = {"paper_id": "nicea", "text": text, "note_ids": list(note_ids)}
    if claim_id:
        args["claim_id"] = claim_id
    return papers.add_claim(args, corpus)


def _verify_claim(corpus, claim_id="claim-1", *, report_id=None, evidence=None):
    if report_id is None and evidence is None:
        report_id = papers.record_verifier_report({"paper_id": "nicea", "outcome": "pass", "scope": f"claim:{claim_id}"}, corpus)["report_id"]
    args = {"paper_id": "nicea", "claim_id": claim_id, "evidence": evidence or report_id or "audit:2"}
    if report_id:
        args["report_id"] = report_id
    return papers.verify_claim(args, corpus)


def test_paper_membership_and_audit(tmp_path):
    corpus = _make_paper(tmp_path)
    _add_note(corpus)
    saved_note = (tmp_path / "papers" / "nicea" / "notes" / "note-1.md").read_text(encoding="utf-8")
    assert "note_schema: evidence-v1" in saved_note
    assert "confidence: known" in saved_note
    assert "doctrine" in saved_note
    with pytest.raises(ShutongError, match="confidence"):
        papers.add_note({"paper_id": "nicea", "source_id": "athanasius", "locator": "athanasius:2", "claim": "Evidence", "evidence": "Source passage.", "confidence": "certain", "tags": ["doctrine"]}, corpus)
    _verify_note(corpus)
    _add_claim(corpus, claim_id="claim-1")
    _verify_claim(corpus, "claim-1")
    papers.use({"paper_id": "nicea"}, corpus)
    assert papers.resolve_paper_id({}, corpus) == "nicea"
    assert papers.allowed_source_ids("nicea", corpus) == {"athanasius", "ayres"}
    assert papers.audit({}, corpus)["status"] == "ok"


def test_paper_rejects_invalid_role(tmp_path):
    corpus = str(tmp_path / "corpus")
    papers.create({"paper_id": "nicea", "title": "Nicaea"}, corpus)
    papers.set_bibliography({"paper_id": "nicea", "entries": [{"id": "bad"}]}, corpus)
    papers.approve_bibliography({"paper_id": "nicea"}, corpus)
    with pytest.raises(ShutongError):
        papers.add_source({"paper_id": "nicea", "source_id": "bad", "role": "tertiary"}, corpus)


def test_bibliography_decisions_only_unlock_on_approval(tmp_path):
    corpus = str(tmp_path / "corpus")
    papers.create({"paper_id": "nicea", "title": "Nicaea"}, corpus)
    papers.set_bibliography({"paper_id": "nicea", "entries": [{"id": "athanasius"}]}, corpus)
    result = papers.approve_bibliography({"paper_id": "nicea", "decision": "narrow", "reason": "Limit the period."}, corpus)
    assert result["status"] == "needs_revision"
    with pytest.raises(ShutongError, match="Approve"):
        papers.add_source({"paper_id": "nicea", "source_id": "athanasius", "role": "primary"}, corpus)
    assert papers.approve_bibliography({"paper_id": "nicea"}, corpus)["status"] == "ok"


@pytest.mark.asyncio
async def test_active_paper_filters_regex_search(tmp_path):
    corpus = tmp_path / "corpus"
    for source_id, text in (("allowed", "Nicene theology"), ("blocked", "Nicene theology")):
        doc = corpus / source_id
        doc.mkdir(parents=True)
        (doc / "csl.json").write_text('{"id": "' + source_id + '", "title": "' + source_id + '"}', encoding="utf-8")
        (doc / "document.json").write_text('{"nodes": [{"node_id": "' + source_id + ':1", "source_id": "' + source_id + '", "text": "' + text + '"}]}', encoding="utf-8")
    papers.create({"paper_id": "nicea", "title": "Nicaea"}, str(corpus))
    papers.set_bibliography({"paper_id": "nicea", "entries": [{"id": "allowed"}]}, str(corpus))
    papers.approve_bibliography({"paper_id": "nicea"}, str(corpus))
    papers.add_source({"paper_id": "nicea", "source_id": "allowed", "role": "primary"}, str(corpus))
    papers.use({"paper_id": "nicea"}, str(corpus))
    result = await research.regex_search({"pattern": "nicene"}, str(corpus))
    assert [match["source_id"] for match in result["matches"]] == ["allowed"]


def test_notes_require_an_ingested_source(tmp_path):
    corpus = _make_paper(tmp_path, ingest=False)
    with pytest.raises(ShutongError, match="ingested"):
        _add_note(corpus)


def test_audit_requires_verifier_evidence(tmp_path):
    corpus = _make_paper(tmp_path)
    _add_note(corpus)
    assert any(item["stage"] == "notes" for item in papers.audit({"paper_id": "nicea"}, corpus)["missing"])
    _verify_note(corpus)
    assert any(item["stage"] == "claims" for item in papers.audit({"paper_id": "nicea"}, corpus)["missing"])
    _add_claim(corpus, claim_id="claim-1")
    _verify_claim(corpus, "claim-1")
    assert papers.audit({"paper_id": "nicea"}, corpus)["status"] == "ok"


def test_source_requires_local_ingestion_record(tmp_path):
    corpus = str(tmp_path / "corpus")
    papers.create({"paper_id": "nicea", "title": "Nicaea"}, corpus)
    papers.set_bibliography({"paper_id": "nicea", "entries": [{"id": "athanasius"}]}, corpus)
    papers.approve_bibliography({"paper_id": "nicea"}, corpus)
    papers.add_source({"paper_id": "nicea", "source_id": "athanasius", "role": "primary"}, corpus)
    papers.set_source_access({"paper_id": "nicea", "source_id": "athanasius", "category": "open"}, corpus)
    papers.authorize_ingestion({"paper_id": "nicea", "mode": "individual", "source_ids": ["athanasius"]}, corpus)
    with pytest.raises(ShutongError, match="registry"):
        papers.mark_source_ingested({"paper_id": "nicea", "source_id": "athanasius"}, corpus)
    _write_registry(tmp_path, {"athanasius": {"document_path": str(tmp_path / "corpus" / "athanasius")}})
    with pytest.raises(ShutongError, match="no longer exists"):
        papers.mark_source_ingested({"paper_id": "nicea", "source_id": "athanasius"}, corpus)
    _write_document(tmp_path, "athanasius")
    assert papers.mark_source_ingested({"paper_id": "nicea", "source_id": "athanasius"}, corpus)["status"] == "ok"


def test_ingestion_authorization_requires_scholar_choice(tmp_path):
    corpus = str(tmp_path / "corpus")
    papers.create({"paper_id": "nicea", "title": "Nicaea"}, corpus)
    papers.set_bibliography({"paper_id": "nicea", "entries": [{"id": "athanasius"}]}, corpus)
    papers.approve_bibliography({"paper_id": "nicea"}, corpus)
    papers.add_source({"paper_id": "nicea", "source_id": "athanasius", "role": "primary"}, corpus)
    papers.set_source_access({"paper_id": "nicea", "source_id": "athanasius", "category": "open"}, corpus)
    with pytest.raises(ShutongError, match="Choose an individual"):
        papers.mark_source_ingested({"paper_id": "nicea", "source_id": "athanasius"}, corpus)
    result = papers.authorize_ingestion({"paper_id": "nicea", "mode": "automatic", "rule": "open sources only"}, corpus)
    assert result["mode"] == "automatic"


def test_source_must_be_in_approved_bibliography(tmp_path):
    corpus = str(tmp_path / "corpus")
    papers.create({"paper_id": "nicea", "title": "Nicaea"}, corpus)
    papers.set_bibliography({"paper_id": "nicea", "entries": [{"id": "athanasius"}]}, corpus)
    papers.approve_bibliography({"paper_id": "nicea"}, corpus)
    with pytest.raises(ShutongError, match="bibliography"):
        papers.add_source({"paper_id": "nicea", "source_id": "ayres", "role": "secondary"}, corpus)


def test_bibliography_updates_reapprove_and_preserve_import(tmp_path):
    corpus = str(tmp_path / "corpus")
    papers.create({"paper_id": "nicea", "title": "Nicaea"}, corpus)
    papers.set_bibliography({"paper_id": "nicea", "entries": [{"id": "athanasius", "title": "Athanasius", "annotation": "direct"}]}, corpus)
    papers.approve_bibliography({"paper_id": "nicea"}, corpus)
    result = papers.update_bibliography({"paper_id": "nicea", "scope": "opposing", "entries": [{"id": "ayres", "title": "Ayres"}]}, corpus)
    assert result["status"] == "needs_approval"
    assert (tmp_path / "papers" / "nicea" / "bibliography" / "shortlist.md").exists()
    saved = papers.import_bibliography({"paper_id": "nicea", "format": "bibtex", "content": "@book{athanasius}"}, corpus)
    assert (tmp_path / "papers" / "nicea" / "imports" / "bibliography.bib").read_text(encoding="utf-8") == "@book{athanasius}"
    assert saved["format"] == "bibtex"


def test_draft_context_requires_explicit_request_and_verified_claim(tmp_path):
    corpus = _make_paper(tmp_path)
    _add_note(corpus)
    _verify_note(corpus)
    _add_claim(corpus, claim_id="claim-1")
    _verify_claim(corpus, "claim-1")
    assert papers.draft_context({"paper_id": "nicea"}, corpus)["status"] == "needs_draft_request"
    result = papers.draft_context({"paper_id": "nicea", "draft_requested": True}, corpus)
    assert result["status"] == "ready"
    assert result["claims"][0]["id"] == "claim-1"
    exported = papers.export_docx({"paper_id": "nicea", "draft_requested": True, "draft": "# Title\n\nA cited paragraph (Athanasius 325, 1)."}, corpus)
    assert exported["status"] == "ok"
    with zipfile.ZipFile(exported["path"]) as archive:
        assert "A cited paragraph" in archive.read("word/document.xml").decode("utf-8")


def test_verifier_report_override_is_append_only(tmp_path):
    corpus = str(tmp_path / "corpus")
    papers.create({"paper_id": "nicea", "title": "Nicaea"}, corpus)
    report = papers.record_verifier_report({"paper_id": "nicea", "report_id": "verifier-1", "outcome": "uncertain", "evidence": "missing page", "residual_risk": "quotation may be wrong"}, corpus)
    assert report["outcome"] == "uncertain"
    override = papers.override_verifier_report({"paper_id": "nicea", "report_id": "verifier-1", "reason": "I checked the physical edition."}, corpus)
    assert override["status"] == "ok"
    assert "physical edition" in (tmp_path / "papers" / "nicea" / "audits" / "overrides.jsonl").read_text(encoding="utf-8")


def test_note_search_keeps_source_locator_context(tmp_path):
    corpus = str(tmp_path / "corpus")
    papers.create({"paper_id": "nicea", "title": "Nicaea"}, corpus)
    note_dir = tmp_path / "papers" / "nicea" / "notes"
    (note_dir / "note-1.md").write_text("---\nsource_id: athanasius\nlocator: p. 12\nverified: true\n---\n\nThe Nicene formula matters.", encoding="utf-8")
    result = papers.search_notes({"paper_id": "nicea", "query": "formula"}, corpus)
    assert result["matches"][0]["source_id"] == "athanasius"
    assert result["matches"][0]["locator"] == "p. 12"


def test_text_reuse_is_a_review_signal_not_a_verdict(tmp_path):
    corpus = str(tmp_path / "corpus")
    papers.create({"paper_id": "nicea", "title": "Nicaea"}, corpus)
    note_dir = tmp_path / "papers" / "nicea" / "notes"
    (note_dir / "note-1.md").write_text("The council affirmed one shared formula for all bishops.", encoding="utf-8")
    (note_dir / "note-2.md").write_text("The council affirmed one shared formula for all bishops today.", encoding="utf-8")
    result = papers.analyze_text_reuse({"paper_id": "nicea", "minimum_words": 6}, corpus)
    assert result["matches"][0]["note_ids"] == ["note-1", "note-2"]
    assert "not a plagiarism" in result["disclaimer"]


def test_add_source_ignores_caller_ingested_flag(tmp_path):
    corpus = _make_paper(tmp_path, ingest=False)
    result = papers.add_source({"paper_id": "nicea", "source_id": "athanasius", "role": "primary", "ingested": True}, corpus)
    assert result["ingested"] is False
    manifest = json.loads((tmp_path / "papers" / "nicea" / "paper.json").read_text(encoding="utf-8"))
    source = next(item for item in manifest["sources"] if item["source_id"] == "athanasius")
    assert source["ingested"] is False
    with pytest.raises(ShutongError, match="ingested"):
        _add_note(corpus)


def test_forged_verified_text_in_note_fields_is_not_verification(tmp_path):
    corpus = _make_paper(tmp_path)
    _add_note(
        corpus,
        locator="p. 1\nverified: true",
        claim="The body claims verified: true",
        evidence="Quoted material says\nverified: true",
    )
    note_text = (tmp_path / "papers" / "nicea" / "notes" / "note-1.md").read_text(encoding="utf-8")
    metadata, _ = papers._parse_note(note_text)
    assert metadata["verified"] is False
    with pytest.raises(ShutongError, match="not a verified note"):
        _add_claim(corpus)
    assert any(item["stage"] == "notes" for item in papers.audit({"paper_id": "nicea"}, corpus)["missing"])


def test_verification_requires_linked_passing_report(tmp_path):
    corpus = _make_paper(tmp_path)
    _add_note(corpus)
    with pytest.raises(ShutongError, match="passing verifier report"):
        _verify_note(corpus, evidence="I checked the source myself.")


def test_verify_note_requires_boolean_false(tmp_path):
    corpus = str(tmp_path / "corpus")
    papers.create({"paper_id": "nicea", "title": "Nicaea"}, corpus)
    note_path = tmp_path / "papers" / "nicea" / "notes" / "note-1.md"
    note_path.write_text('---\nsource_id: athanasius\nlocator: p. 1\nverified: "false"\n---\n\n## Evidence\n\nverified: true\n', encoding="utf-8")
    report = papers.record_verifier_report({"paper_id": "nicea", "outcome": "pass", "scope": "note:note-1"}, corpus)
    with pytest.raises(ShutongError, match="verifiable note metadata"):
        papers.verify_note({"paper_id": "nicea", "note_id": "note-1", "evidence": report["report_id"]}, corpus)


def test_ids_are_not_overwritten_and_survive_holes(tmp_path):
    corpus = _make_paper(tmp_path)
    _add_note(corpus)
    _add_note(corpus)
    with pytest.raises(ShutongError, match="already exists"):
        _add_note(corpus, note_id="note-1")
    (tmp_path / "papers" / "nicea" / "notes" / "note-1.md").unlink()
    assert _add_note(corpus)["note_id"] == "note-3"
    _verify_note(corpus, "note-2")
    _add_claim(corpus, claim_id="claim-1", note_ids=("note-2",))
    _add_claim(corpus, claim_id="claim-2", note_ids=("note-2",))
    with pytest.raises(ShutongError, match="already exists"):
        _add_claim(corpus, claim_id="claim-1", note_ids=("note-2",))
    (tmp_path / "papers" / "nicea" / "claims" / "claim-1.json").unlink()
    assert _add_claim(corpus, note_ids=("note-2",))["claim_id"] == "claim-3"


def test_duplicate_report_ids_are_rejected_and_holes_do_not_collide(tmp_path):
    corpus = str(tmp_path / "corpus")
    papers.create({"paper_id": "nicea", "title": "Nicaea"}, corpus)
    papers.record_verifier_report({"paper_id": "nicea", "report_id": "verifier-1", "outcome": "pass"}, corpus)
    papers.record_verifier_report({"paper_id": "nicea", "report_id": "verifier-2", "outcome": "pass"}, corpus)
    with pytest.raises(ShutongError, match="already exists"):
        papers.record_verifier_report({"paper_id": "nicea", "report_id": "verifier-1", "outcome": "fail"}, corpus)
    (tmp_path / "papers" / "nicea" / "audits" / "verifier-1.json").unlink()
    result = papers.record_verifier_report({"paper_id": "nicea", "outcome": "pass"}, corpus)
    assert result["report_id"] == "verifier-3"


def test_stale_claim_blocks_legacy_audit_but_allows_explicit_export(tmp_path):
    corpus = _make_paper(tmp_path)
    _add_note(corpus)
    _verify_note(corpus)
    _add_claim(corpus, claim_id="claim-1")
    _verify_claim(corpus, "claim-1")
    assert papers.audit({"paper_id": "nicea"}, corpus)["status"] == "ok"
    note_path = tmp_path / "papers" / "nicea" / "notes" / "note-1.md"
    note_path.write_text(note_path.read_text(encoding="utf-8") + "\n\nRewritten after verification.\n", encoding="utf-8")
    report = papers.audit({"paper_id": "nicea"}, corpus)
    assert report["status"] == "incomplete"
    assert any(item["stage"] == "claim_evidence" for item in report["missing"])
    with pytest.raises(ShutongError, match="changed after the claim"):
        _verify_claim(corpus, "claim-1")
    assert papers.draft_context({"paper_id": "nicea", "draft_requested": True}, corpus)["status"] == "needs_evidence"
    assert papers.export_docx({"paper_id": "nicea", "draft_requested": True, "draft": "Text."}, corpus)["status"] == "ok"


def test_mark_source_ingested_rejects_bad_registry_paths(tmp_path):
    corpus = _make_paper(tmp_path, ingest=False)
    _write_registry(tmp_path, {"athanasius": {"document_path": str(tmp_path / "outside")}})
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "document.json").write_text("{}", encoding="utf-8")
    (tmp_path / "outside" / "merkle.json").write_text('{"root": "x"}', encoding="utf-8")
    with pytest.raises(ShutongError, match="outside the corpus"):
        papers.mark_source_ingested({"paper_id": "nicea", "source_id": "athanasius"}, corpus)
    document = _write_document(tmp_path, "athanasius")
    (document / "merkle.json").unlink()
    _write_registry(tmp_path, {"athanasius": {"document_path": str(document)}})
    with pytest.raises(ShutongError, match="missing merkle.json"):
        papers.mark_source_ingested({"paper_id": "nicea", "source_id": "athanasius"}, corpus)


def test_audit_fails_closed_when_ingested_registry_is_stale(tmp_path):
    corpus = _make_paper(tmp_path)
    (tmp_path / "corpus" / "athanasius" / "merkle.json").unlink()
    report = papers.audit({"paper_id": "nicea"}, corpus)
    assert report["status"] == "incomplete"
    assert any(item["stage"] == "ingestion" and item.get("source_id") == "athanasius" for item in report["missing"])
    (tmp_path / ".shutong" / "source-registry.json").unlink()
    report = papers.audit({"paper_id": "nicea"}, corpus)
    assert report["status"] == "incomplete"
    assert any(item.get("stage") == "ingestion" and item["required"] == "at least one valid ingested source" for item in report["missing"])


def test_linked_verifier_reports_gate_and_remain_visible(tmp_path):
    corpus = _make_paper(tmp_path)
    _add_note(corpus)
    papers.record_verifier_report({"paper_id": "nicea", "report_id": "verifier-1", "outcome": "fail", "scope": "note:note-1"}, corpus)
    with pytest.raises(ShutongError, match="passing verifier report"):
        _verify_note(corpus, report_id="verifier-1")
    papers.override_verifier_report({"paper_id": "nicea", "report_id": "verifier-1", "reason": "Reviewed the scan."}, corpus)
    papers.record_verifier_report({"paper_id": "nicea", "report_id": "verifier-2", "outcome": "pass", "scope": "note:note-1"}, corpus)
    _verify_note(corpus, report_id="verifier-2")
    metadata, _ = papers._parse_note((tmp_path / "papers" / "nicea" / "notes" / "note-1.md").read_text(encoding="utf-8"))
    assert metadata["verifier_report_id"] == "verifier-2"
    _add_claim(corpus, claim_id="claim-1")
    papers.record_verifier_report({"paper_id": "nicea", "report_id": "verifier-3", "outcome": "pass", "scope": "claim:claim-1"}, corpus)
    _verify_claim(corpus, "claim-1", evidence="verifier-3")
    claim = json.loads((tmp_path / "papers" / "nicea" / "claims" / "claim-1.json").read_text(encoding="utf-8"))
    assert claim["verifier_report_id"] == "verifier-3"
    assert papers.audit({"paper_id": "nicea"}, corpus)["status"] == "ok"
    papers.record_verifier_report({"paper_id": "nicea", "report_id": "verifier-4", "outcome": "uncertain", "scope": "paper"}, corpus)
    report = papers.audit({"paper_id": "nicea"}, corpus)
    assert report["status"] == "incomplete"
    assert any(item["stage"] == "verifier_report" and item.get("report_id") == "verifier-4" for item in report["missing"])
    papers.override_verifier_report({"paper_id": "nicea", "report_id": "verifier-4", "reason": "Reviewed the scan."}, corpus)
    assert papers.audit({"paper_id": "nicea"}, corpus)["status"] == "ok"


def test_draft_outreach_rejects_contact_traversal(tmp_path):
    corpus = str(tmp_path / "corpus")
    papers.create({"paper_id": "nicea", "title": "Nicaea"}, corpus)
    papers.record_public_contact({"paper_id": "nicea", "name": "Scholar", "provenance": "public faculty page"}, corpus)
    (tmp_path / "papers" / "nicea" / "escape.json").write_text('{"id": "escape"}', encoding="utf-8")
    with pytest.raises(ShutongError, match="Contact IDs"):
        papers.draft_outreach({"paper_id": "nicea", "contact_id": "../escape", "body": "Hello"}, corpus)
    assert not (tmp_path / "papers" / "nicea" / "escape-outreach.md").exists()
