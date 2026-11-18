from __future__ import annotations

import zipfile

import pytest

from shutong_backend import papers
from shutong_backend import workspaces
from shutong_backend.tools import research
from shutong_backend.tools.errors import ShutongError


def test_paper_membership_and_audit(tmp_path):
    corpus = str(tmp_path / "corpus")
    papers.create({"paper_id": "nicea", "title": "Nicaea"}, corpus)
    papers.set_bibliography({"paper_id": "nicea", "entries": [{"id": "athanasius"}, {"id": "ayres"}]}, corpus)
    papers.approve_bibliography({"paper_id": "nicea"}, corpus)
    papers.add_source({"paper_id": "nicea", "source_id": "athanasius", "role": "primary", "ingested": True}, corpus)
    papers.add_source({"paper_id": "nicea", "source_id": "ayres", "role": "secondary", "ingested": True}, corpus)
    papers.add_note({"paper_id": "nicea", "source_id": "athanasius", "locator": "athanasius:1", "claim": "Evidence", "evidence": "Source passage.", "confidence": "known", "tags": ["doctrine"]}, corpus)
    saved_note = (tmp_path / "papers" / "nicea" / "notes" / "note-1.md").read_text(encoding="utf-8")
    assert "note_schema: evidence-v1" in saved_note
    assert "confidence: known" in saved_note
    assert 'tags: ["doctrine"]' in saved_note
    with pytest.raises(ShutongError, match="confidence"):
        papers.add_note({"paper_id": "nicea", "source_id": "athanasius", "locator": "athanasius:2", "claim": "Evidence", "evidence": "Source passage.", "confidence": "certain", "tags": ["doctrine"]}, corpus)
    papers.verify_note({"paper_id": "nicea", "note_id": "note-1", "evidence": "audit:1"}, corpus)
    papers.add_claim({"paper_id": "nicea", "claim_id": "claim-1", "text": "Evidence supports the paper.", "note_ids": ["note-1"]}, corpus)
    papers.verify_claim({"paper_id": "nicea", "claim_id": "claim-1", "evidence": "audit:2"}, corpus)
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
    papers.add_source({"paper_id": "nicea", "source_id": "allowed", "role": "primary", "ingested": True}, str(corpus))
    papers.use({"paper_id": "nicea"}, str(corpus))
    result = await research.regex_search({"pattern": "nicene"}, str(corpus))
    assert [match["source_id"] for match in result["matches"]] == ["allowed"]


def test_notes_require_an_ingested_source(tmp_path):
    corpus = str(tmp_path / "corpus")
    papers.create({"paper_id": "nicea", "title": "Nicaea"}, corpus)
    papers.set_bibliography({"paper_id": "nicea", "entries": [{"id": "athanasius"}, {"id": "ayres"}]}, corpus)
    papers.approve_bibliography({"paper_id": "nicea"}, corpus)
    papers.add_source({"paper_id": "nicea", "source_id": "athanasius", "role": "primary"}, corpus)
    papers.set_source_access({"paper_id": "nicea", "source_id": "athanasius", "category": "open", "provenance": "publisher OA page"}, corpus)
    with pytest.raises(ShutongError, match="ingested"):
        papers.add_note({"paper_id": "nicea", "source_id": "athanasius", "locator": "1", "claim": "x", "evidence": "Source passage.", "confidence": "known", "tags": ["doctrine"]}, corpus)


def test_audit_requires_verifier_evidence(tmp_path):
    corpus = str(tmp_path / "corpus")
    papers.create({"paper_id": "nicea", "title": "Nicaea"}, corpus)
    papers.set_bibliography({"paper_id": "nicea", "entries": [{"id": "athanasius"}, {"id": "ayres"}]}, corpus)
    papers.approve_bibliography({"paper_id": "nicea"}, corpus)
    papers.add_source({"paper_id": "nicea", "source_id": "athanasius", "role": "primary", "ingested": True}, corpus)
    papers.add_source({"paper_id": "nicea", "source_id": "ayres", "role": "secondary", "ingested": True}, corpus)
    papers.add_note({"paper_id": "nicea", "source_id": "athanasius", "locator": "1", "claim": "x", "evidence": "Source passage.", "confidence": "known", "tags": ["doctrine"]}, corpus)
    assert any(item["stage"] == "notes" for item in papers.audit({"paper_id": "nicea"}, corpus)["missing"])
    papers.verify_note({"paper_id": "nicea", "note_id": "note-1", "evidence": "audit:1"}, corpus)
    assert any(item["stage"] == "claims" for item in papers.audit({"paper_id": "nicea"}, corpus)["missing"])
    papers.add_claim({"paper_id": "nicea", "text": "Evidence supports the paper.", "note_ids": ["note-1"]}, corpus)
    papers.verify_claim({"paper_id": "nicea", "claim_id": "claim-1", "evidence": "audit:2"}, corpus)
    assert papers.audit({"paper_id": "nicea"}, corpus)["status"] == "ok"


def test_source_requires_local_ingestion_record(tmp_path):
    corpus = str(tmp_path / "corpus")
    papers.create({"paper_id": "nicea", "title": "Nicaea"}, corpus)
    papers.set_bibliography({"paper_id": "nicea", "entries": [{"id": "athanasius"}]}, corpus)
    papers.approve_bibliography({"paper_id": "nicea"}, corpus)
    papers.add_source({"paper_id": "nicea", "source_id": "athanasius", "role": "primary"}, corpus)
    papers.set_source_access({"paper_id": "nicea", "source_id": "athanasius", "category": "open"}, corpus)
    papers.authorize_ingestion({"paper_id": "nicea", "mode": "individual", "source_ids": ["athanasius"]}, corpus)
    with pytest.raises(ShutongError, match="ingestion record"):
        papers.mark_source_ingested({"paper_id": "nicea", "source_id": "athanasius"}, corpus)
    registry = tmp_path / ".shutong" / "source-registry.json"
    registry.parent.mkdir()
    registry.write_text('{"athanasius": {"document_path": "corpus/athanasius"}}', encoding="utf-8")
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
    corpus = str(tmp_path / "corpus")
    papers.create({"paper_id": "nicea", "title": "Nicaea"}, corpus)
    papers.set_bibliography({"paper_id": "nicea", "entries": [{"id": "athanasius"}, {"id": "ayres"}]}, corpus)
    papers.approve_bibliography({"paper_id": "nicea"}, corpus)
    for source_id, role in (("athanasius", "primary"), ("ayres", "secondary")):
        papers.add_source({"paper_id": "nicea", "source_id": source_id, "role": role, "ingested": True}, corpus)
    papers.add_note({"paper_id": "nicea", "source_id": "athanasius", "locator": "1", "claim": "Evidence", "evidence": "Source passage.", "confidence": "known", "tags": ["doctrine"]}, corpus)
    papers.verify_note({"paper_id": "nicea", "note_id": "note-1", "evidence": "audit:1"}, corpus)
    papers.add_claim({"paper_id": "nicea", "claim_id": "claim-1", "text": "Evidence supports the paper.", "note_ids": ["note-1"]}, corpus)
    papers.verify_claim({"paper_id": "nicea", "claim_id": "claim-1", "evidence": "audit:2"}, corpus)
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


def test_public_contacts_keep_provenance_and_outreach_is_not_sent(tmp_path):
    corpus = str(tmp_path / "corpus")
    papers.create({"paper_id": "nicea", "title": "Nicaea"}, corpus)
    contact = papers.record_public_contact({"paper_id": "nicea", "contact_id": "contact-1", "name": "Scholar", "email": "scholar@example.edu", "provenance": "https://example.edu/profile"}, corpus)
    drafted = papers.draft_outreach({"paper_id": "nicea", "contact_id": contact["contact_id"], "body": "Dear Scholar,"}, corpus)
    assert drafted["status"] == "drafted_not_sent"
    assert (tmp_path / "papers" / "nicea" / "contacts" / "contact-1-outreach.md").exists()


def test_paper_evidence_lineage_reaches_explicit_docx_export(tmp_path):
    corpus = str(tmp_path / "corpus")
    papers.create({"paper_id": "nicea", "title": "Nicaea"}, corpus)
    papers.set_bibliography({"paper_id": "nicea", "entries": [{"id": "athanasius"}, {"id": "ayres"}]}, corpus)
    papers.approve_bibliography({"paper_id": "nicea"}, corpus)
    for source_id, role in (("athanasius", "primary"), ("ayres", "secondary")):
        papers.add_source({"paper_id": "nicea", "source_id": source_id, "role": role}, corpus)
        papers.set_source_access({"paper_id": "nicea", "source_id": source_id, "category": "open"}, corpus)
    papers.authorize_ingestion({"paper_id": "nicea", "mode": "batch", "source_ids": ["athanasius", "ayres"]}, corpus)
    registry = tmp_path / ".shutong" / "source-registry.json"
    registry.parent.mkdir()
    registry.write_text('{"athanasius": {"document_path": "corpus/athanasius"}, "ayres": {"document_path": "corpus/ayres"}}', encoding="utf-8")
    for source_id in ("athanasius", "ayres"):
        papers.mark_source_ingested({"paper_id": "nicea", "source_id": source_id}, corpus)
    papers.add_note({"paper_id": "nicea", "source_id": "athanasius", "locator": "p. 1", "claim": "The source supports the claim.", "evidence": "A direct quotation.", "confidence": "known", "tags": ["doctrine"]}, corpus)
    papers.verify_note({"paper_id": "nicea", "note_id": "note-1", "evidence": "verified against p. 1"}, corpus)
    papers.add_claim({"paper_id": "nicea", "claim_id": "claim-1", "text": "The source supports the claim.", "note_ids": ["note-1"]}, corpus)
    papers.verify_claim({"paper_id": "nicea", "claim_id": "claim-1", "evidence": "claim aligns with note-1"}, corpus)
    exported = papers.export_docx({"paper_id": "nicea", "draft_requested": True, "draft": "The source supports the claim (Athanasius 325, 1)."}, corpus)
    assert exported["status"] == "ok"
    assert papers.audit({"paper_id": "nicea"}, corpus)["status"] == "ok"


def test_book_chapters_share_sources_but_not_notes_or_claims(tmp_path):
    corpus = str(tmp_path / "corpus")
    workspaces.create_project({"project_id": "augustine-book", "title": "Augustine", "kind": "book"}, corpus)
    for work_id, title in (("chapter-one", "Chapter One"), ("chapter-two", "Chapter Two")):
        workspaces.create_work({"project_id": "augustine-book", "work_id": work_id, "title": title}, corpus)
    papers.set_bibliography({"paper_id": "chapter-one", "entries": [{"id": "confessions"}]}, corpus)
    papers.approve_bibliography({"paper_id": "chapter-one"}, corpus)
    papers.add_source({"paper_id": "chapter-one", "source_id": "confessions", "role": "primary", "ingested": True}, corpus)
    assert papers.allowed_source_ids("chapter-two", corpus) == {"confessions"}
    papers.add_note({"paper_id": "chapter-one", "source_id": "confessions", "locator": "I.1", "claim": "A chapter-one note.", "evidence": "Source passage.", "confidence": "known", "tags": ["autobiography"]}, corpus)
    assert papers.search_notes({"paper_id": "chapter-two", "query": "chapter-one"}, corpus)["matches"] == []


def test_workspace_planner_requires_confirmation_to_switch(tmp_path):
    corpus = str(tmp_path / "corpus")
    workspaces.create_project({"project_id": "book", "title": "Augustine", "kind": "book"}, corpus)
    workspaces.create_work({"project_id": "book", "work_id": "confessions-chapter", "title": "Confessions"}, corpus)
    plan = workspaces.plan_switch({"query": "work on confessions-chapter now"}, corpus)
    assert plan["action"] == "confirm_switch"
    with pytest.raises(ShutongError, match="Confirm"):
        workspaces.activate({"project_id": "book", "work_id": "confessions-chapter"}, corpus)
    assert workspaces.activate({"project_id": "book", "work_id": "confessions-chapter", "confirmed": True}, corpus)["active"]["work_id"] == "confessions-chapter"
