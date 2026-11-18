"""Project-local paper manifests and source membership."""

from __future__ import annotations

import json
import re
import zipfile
from html import escape
from pathlib import Path
from typing import Any

from shutong_backend.tools.errors import ShutongError

_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_ROLES = {"primary", "secondary", "unknown"}
_ACCESS = {"open", "licensed", "user-provided", "metadata-only", "restricted", "unavailable"}
_NOTE_CONFIDENCE = {"known", "probable", "speculative"}


def project_root(corpus_root: str) -> Path:
    return Path(corpus_root).resolve().parent


def _paper_path(corpus_root: str, paper_id: str) -> Path:
    if not _ID.fullmatch(paper_id):
        raise ShutongError("invalid_paper_id", "Paper IDs use lowercase letters, numbers, and hyphens.")
    return project_root(corpus_root) / "papers" / paper_id / "paper.json"


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ShutongError("paper_not_found", f"Paper not found: {path.parent.name}", "Create it with shutong paper create.")
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, paper: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(paper, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _source_path(path: Path, paper: dict[str, Any], corpus_root: str) -> Path:
    """Return a work's source library, which a book chapter shares with its project."""
    source_workspace_id = paper.get("source_workspace_id")
    return _paper_path(corpus_root, source_workspace_id) if source_workspace_id else path


def _source_paper(path: Path, paper: dict[str, Any], corpus_root: str) -> tuple[Path, dict[str, Any]]:
    source_path = _source_path(path, paper, corpus_root)
    return source_path, _read(source_path)


def _validate_entries(entries: Any) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        raise ShutongError("invalid_bibliography", "Bibliography entries must be a list.")
    if any(not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not entry["id"].strip() for entry in entries):
        raise ShutongError("invalid_bibliography", "Each bibliography entry needs a stable non-empty id.")
    return entries


def _required_note_text(args: dict[str, Any], field: str, message: str) -> str:
    value = args.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ShutongError("invalid_note", message)
    return value.strip()


def _write_bibliography_artifacts(path: Path, entries: list[dict[str, Any]]) -> None:
    directory = path.parent / "bibliography"
    directory.mkdir(exist_ok=True)
    (directory / "shortlist.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Bibliography shortlist", ""]
    for entry in entries:
        title = entry.get("title") or entry["id"]
        annotation = entry.get("annotation") or entry.get("rationale") or ""
        lines.extend((f"## {title}", f"- ID: `{entry['id']}`", f"- Proposed role: {entry.get('role', 'unknown')}", f"- Annotation: {annotation}", ""))
    (directory / "shortlist.md").write_text("\n".join(lines), encoding="utf-8")


def active_paper_id(corpus_root: str) -> str | None:
    path = project_root(corpus_root) / ".shutong" / "active-paper"
    return path.read_text(encoding="utf-8").strip() if path.exists() else None


def resolve_paper_id(args: dict[str, Any], corpus_root: str) -> str | None:
    if args.get("library_wide"):
        return None
    return args.get("paper_id") or active_paper_id(corpus_root)


def create(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    paper_id = args["paper_id"]
    path = _paper_path(corpus_root, paper_id)
    if path.exists():
        raise ShutongError("paper_exists", f"Paper already exists: {paper_id}")
    paper = {"id": paper_id, "title": args["title"], "question": args.get("question", ""), "sources": [], "bibliography": {"status": "draft", "entries": []}, "ingestion": {"mode": None, "authorized_source_ids": []}, "policy": {"minimum_primary": args.get("minimum_primary", 1), "minimum_secondary": args.get("minimum_secondary", 1)}}
    _write(path, paper)
    (path.parent / "drafts").mkdir(exist_ok=True)
    for name in ("notes", "claims", "audits", "imports", "bibliography", "contacts"):
        (path.parent / name).mkdir(exist_ok=True)
    return {"status": "ok", "paper": paper, "path": str(path)}


def add_source(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    role = args.get("role", "unknown")
    if role not in _ROLES:
        raise ShutongError("invalid_source_role", "Source role must be primary, secondary, or unknown.")
    path = _paper_path(corpus_root, args["paper_id"])
    paper = _read(path)
    source_path, source_paper = _source_paper(path, paper, corpus_root)
    if source_paper.get("bibliography", {}).get("status") != "approved":
        raise ShutongError("bibliography_not_approved", "Approve the bibliography before ingesting or adding a paper source.")
    source_id = args["source_id"]
    bibliography_ids = {entry["id"] for entry in source_paper["bibliography"]["entries"]}
    if source_id not in bibliography_ids:
        raise ShutongError("source_not_in_bibliography", "Add the source to the approved bibliography before assigning it to this paper.")
    source_paper["sources"] = [item for item in source_paper["sources"] if item["source_id"] != source_id]
    source_paper["sources"].append({"source_id": source_id, "role": role, "ingested": bool(args.get("ingested", False))})
    _write(source_path, source_paper)
    return {"status": "ok", "paper_id": paper["id"], "source_workspace_id": source_paper["id"], "source_id": source_id, "role": role}


def mark_source_ingested(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    """Link a paper source to the local ingestion record; callers cannot merely assert it."""
    path = _paper_path(corpus_root, args["paper_id"])
    paper = _read(path)
    source_path, source_paper = _source_paper(path, paper, corpus_root)
    source_id = args["source_id"]
    source = next((item for item in source_paper["sources"] if item["source_id"] == source_id), None)
    if source is None:
        raise ShutongError("source_not_in_paper", "Add the approved bibliography source to the paper before marking it ingested.")
    entry = next(item for item in source_paper["bibliography"]["entries"] if item["id"] == source_id)
    access = entry.get("access", {}).get("category")
    if access not in {"open", "licensed", "user-provided"}:
        raise ShutongError("source_not_authorized", "Ingestion requires an open, licensed, or user-provided access record.")
    authorization = source_paper.get("ingestion", {})
    if authorization.get("mode") in {"individual", "batch"} and source_id not in authorization.get("authorized_source_ids", []):
        raise ShutongError("source_not_authorized", "The scholar has not authorized ingestion for this source.")
    if authorization.get("mode") not in {"individual", "batch", "automatic"}:
        raise ShutongError("ingestion_not_authorized", "Choose an individual, batch, or automatic ingestion authorization first.")
    registry_path = project_root(corpus_root) / ".shutong" / "source-registry.json"
    records = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else {}
    record = records.get(source_id, {})
    if not record.get("document_path"):
        raise ShutongError("ingestion_not_found", f"No local ingestion record found for source: {source_id}")
    source["ingested"] = True
    _write(source_path, source_paper)
    return {"status": "ok", "paper_id": paper["id"], "source_workspace_id": source_paper["id"], "source_id": source_id}


def set_bibliography(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    """Save a bibliography shortlist; only an explicit approval unlocks sources."""
    path = _paper_path(corpus_root, args["paper_id"])
    paper = _read(path)
    source_path, source_paper = _source_paper(path, paper, corpus_root)
    entries = _validate_entries(args.get("entries", []))
    source_paper["bibliography"] = {"status": "draft", "entries": entries}
    _write(source_path, source_paper)
    _write_bibliography_artifacts(source_path, entries)
    return {"status": "needs_approval", "paper_id": paper["id"], "source_workspace_id": source_paper["id"], "entry_count": len(entries)}


def update_bibliography(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    """Add scholar-requested contextual, opposing, or critical entries and require reapproval."""
    scope = args.get("scope")
    if scope not in {"contextual", "opposing", "critical"}:
        raise ShutongError("invalid_bibliography_scope", "Updates must be contextual, opposing, or critical.")
    path = _paper_path(corpus_root, args["paper_id"])
    paper = _read(path)
    source_path, source_paper = _source_paper(path, paper, corpus_root)
    additions = _validate_entries(args.get("entries", []))
    existing = {entry["id"]: entry for entry in source_paper.get("bibliography", {}).get("entries", [])}
    for entry in additions:
        existing[entry["id"]] = {**entry, "scope": scope}
    entries = list(existing.values())
    source_paper["bibliography"] = {"status": "draft", "entries": entries}
    _write(source_path, source_paper)
    _write_bibliography_artifacts(source_path, entries)
    return {"status": "needs_approval", "paper_id": paper["id"], "source_workspace_id": source_paper["id"], "entry_count": len(entries), "scope": scope}


def import_bibliography(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    """Preserve a scholar's original BibTeX or CSL-JSON import without normalizing it away."""
    kind = args.get("format")
    if kind not in {"bibtex", "csl-json"}:
        raise ShutongError("invalid_bibliography_format", "Bibliography imports must be BibTeX or CSL-JSON.")
    content = args.get("content", "")
    if not isinstance(content, str) or not content.strip():
        raise ShutongError("empty_bibliography_import", "A bibliography import cannot be empty.")
    path = _paper_path(corpus_root, args["paper_id"])
    source_path, _ = _source_paper(path, _read(path), corpus_root)
    suffix = "bib" if kind == "bibtex" else "json"
    import_path = source_path.parent / "imports" / f"bibliography.{suffix}"
    import_path.write_text(content, encoding="utf-8")
    return {"status": "ok", "paper_id": args["paper_id"], "format": kind, "path": str(import_path)}


def set_source_access(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    """Record a lawful access classification before an ingestion choice is made."""
    category = args.get("category")
    if category not in _ACCESS:
        raise ShutongError("invalid_access_category", "Access category must be open, licensed, user-provided, metadata-only, restricted, or unavailable.")
    path = _paper_path(corpus_root, args["paper_id"])
    paper = _read(path)
    source_path, source_paper = _source_paper(path, paper, corpus_root)
    source_id = args["source_id"]
    entry = next((item for item in source_paper.get("bibliography", {}).get("entries", []) if item["id"] == source_id), None)
    if entry is None:
        raise ShutongError("source_not_in_bibliography", "Record access only for a bibliography entry in this paper.")
    entry["access"] = {"category": category, "provenance": args.get("provenance", "")}
    _write(source_path, source_paper)
    return {"status": "ok", "paper_id": paper["id"], "source_id": source_id, "category": category}


def authorize_ingestion(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    """Record the scholar's individual, batch, or explicit automatic ingestion authorization."""
    mode = args.get("mode")
    if mode not in {"individual", "batch", "automatic"}:
        raise ShutongError("invalid_ingestion_mode", "Ingestion mode must be individual, batch, or automatic.")
    path = _paper_path(corpus_root, args["paper_id"])
    paper = _read(path)
    source_path, source_paper = _source_paper(path, paper, corpus_root)
    source_ids = args.get("source_ids", [])
    bibliography_ids = {entry["id"] for entry in source_paper.get("bibliography", {}).get("entries", [])}
    if mode in {"individual", "batch"} and (not isinstance(source_ids, list) or not source_ids or not set(source_ids) <= bibliography_ids):
        raise ShutongError("invalid_ingestion_authorization", "Individual and batch authorization require bibliography source IDs.")
    rule = args.get("rule", "").strip()
    if mode == "automatic" and not rule:
        raise ShutongError("missing_ingestion_rule", "Automatic ingestion requires a scholar-approved rule.")
    source_paper["ingestion"] = {"mode": mode, "authorized_source_ids": source_ids, "rule": rule}
    _write(source_path, source_paper)
    return {"status": "ok", "paper_id": paper["id"], "mode": mode, "authorized_source_ids": source_ids}


def record_public_contact(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    """Store only a publicly published professional contact with its provenance."""
    path = _paper_path(corpus_root, args["paper_id"])
    _read(path)
    name = args.get("name", "").strip()
    provenance = args.get("provenance", "").strip()
    if not name or not provenance:
        raise ShutongError("missing_contact_provenance", "Public contacts require a name and the public page where the contact was published.")
    contact_id = args.get("contact_id") or f"contact-{len(list(path.parent.joinpath('contacts').glob('*.json'))) + 1}"
    if not _ID.fullmatch(contact_id):
        raise ShutongError("invalid_contact_id", "Contact IDs use lowercase letters, numbers, and hyphens.")
    contact = {"id": contact_id, "name": name, "email": args.get("email", ""), "affiliation": args.get("affiliation", ""), "related_work": args.get("related_work", ""), "provenance": provenance}
    (path.parent / "contacts" / f"{contact_id}.json").write_text(json.dumps(contact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "ok", "paper_id": args["paper_id"], "contact_id": contact_id}


def draft_outreach(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    """Create a local outreach draft; sending email is deliberately out of scope."""
    path = _paper_path(corpus_root, args["paper_id"])
    _read(path)
    contact_id = args["contact_id"]
    contact_path = path.parent / "contacts" / f"{contact_id}.json"
    if not contact_path.exists():
        raise ShutongError("contact_not_found", f"Contact not found: {contact_id}")
    body = args.get("body", "").strip()
    if not body:
        raise ShutongError("empty_outreach_draft", "Outreach drafts require a message body for scholar review.")
    draft_path = path.parent / "contacts" / f"{contact_id}-outreach.md"
    draft_path.write_text(f"# Unsent outreach draft\n\nContact: {contact_id}\n\n{body}\n", encoding="utf-8")
    return {"status": "drafted_not_sent", "paper_id": args["paper_id"], "path": str(draft_path)}


def approve_bibliography(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    """Record the scholar's bibliography decision; only approval unlocks sources."""
    path = _paper_path(corpus_root, args["paper_id"])
    paper = _read(path)
    source_path, source_paper = _source_paper(path, paper, corpus_root)
    bibliography = source_paper.get("bibliography", {})
    if not bibliography.get("entries"):
        raise ShutongError("empty_bibliography", "Save bibliography entries before approval.")
    decision = args.get("decision", "approve")
    if decision not in {"approve", "narrow", "expand", "reject", "correct-classification"}:
        raise ShutongError("invalid_bibliography_decision", "Choose approve, narrow, expand, reject, or correct-classification.")
    if decision == "approve":
        bibliography["status"] = "approved"
    elif decision == "reject":
        bibliography["status"] = "rejected"
    else:
        bibliography["status"] = "revision_requested"
    record = {"decision": decision, "reason": args.get("reason", "").strip()}
    audit_path = source_path.parent / "audits" / "bibliography-decisions.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")
    _write(source_path, source_paper)
    return {"status": "ok" if decision == "approve" else "needs_revision", "paper_id": paper["id"], "decision": decision, "entry_count": len(bibliography["entries"])}


def add_note(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    path = _paper_path(corpus_root, args["paper_id"])
    paper = _read(path)
    source_id = args["source_id"]
    _, source_paper = _source_paper(path, paper, corpus_root)
    source = next((item for item in source_paper["sources"] if item["source_id"] == source_id), None)
    if source is None or not source.get("ingested"):
        raise ShutongError("source_not_ingested", "Notes require an approved, properly ingested paper source.")
    note_id = args.get("note_id") or f"note-{len(list(path.parent.joinpath('notes').glob('*.md'))) + 1}"
    if not isinstance(note_id, str) or not _ID.fullmatch(note_id):
        raise ShutongError("invalid_note_id", "Note IDs use lowercase letters, numbers, and hyphens.")
    analysis_header = ""
    if args.get("analysis_id"):
        from shutong_backend import analysis
        record = analysis.get(args, corpus_root)["analysis"]
        if source_id not in {s["source_id"] for s in record["sources"]}:
            raise ShutongError("analysis_source_mismatch", "The note source is outside the analysis source set.")
        analysis_header = f"analysis_id: {record['analysis_id']}\n"
    locator = _required_note_text(args, "locator", "Notes require a corpus locator.")
    claim = _required_note_text(args, "claim", "Notes require one atomic claim.")
    evidence = _required_note_text(args, "evidence", "Notes require source evidence or a tight paraphrase.")
    confidence = args.get("confidence")
    if confidence not in _NOTE_CONFIDENCE:
        raise ShutongError("invalid_note_confidence", "Note confidence must be known, probable, or speculative.")
    tags = args.get("tags")
    if not isinstance(tags, list) or not tags or any(not isinstance(tag, str) or not tag.strip() for tag in tags):
        raise ShutongError("invalid_note_tags", "Notes require one or more non-empty tags.")
    note_path = path.parent / "notes" / f"{note_id}.md"
    note_path.write_text(
        f"---\nsource_id: {source_id}\nlocator: {locator}\nnote_schema: evidence-v1\nconfidence: {confidence}\ntags: {json.dumps(tags, ensure_ascii=False)}\n{analysis_header}verified: false\n---\n\n"
        f"## Claim\n\n{claim}\n\n## Evidence\n\n{evidence}\n",
        encoding="utf-8",
    )
    return {"status": "ok", "paper_id": paper["id"], "note_id": note_id}


def search_notes(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    """Find a keyword in private paper notes with enough surrounding context to inspect it."""
    path = _paper_path(corpus_root, args["paper_id"])
    _read(path)
    query = args.get("query", "").strip()
    if not query:
        raise ShutongError("empty_note_query", "Note search requires a keyword or phrase.")
    radius = min(max(int(args.get("context", 120)), 20), 500)
    matches = []
    for note_path in sorted((path.parent / "notes").glob("*.md")):
        text = note_path.read_text(encoding="utf-8")
        lowered = text.casefold()
        start = lowered.find(query.casefold())
        if start < 0:
            continue
        header = dict(re.findall(r"^(source_id|locator|confidence|tags): (.+)$", text, re.MULTILINE))
        matches.append({"note_id": note_path.stem, "source_id": header.get("source_id", ""), "locator": header.get("locator", ""), "confidence": header.get("confidence", ""), "tags": header.get("tags", ""), "snippet": text[max(0, start - radius):start + len(query) + radius]})
    return {"status": "ok", "paper_id": args["paper_id"], "query": query, "matches": matches}


def analyze_text_reuse(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    """Surface repeated private-note passages for scholar review; this is not a plagiarism verdict."""
    path = _paper_path(corpus_root, args["paper_id"])
    _read(path)
    width = min(max(int(args.get("minimum_words", 8)), 4), 30)
    windows: dict[tuple[str, ...], set[str]] = {}
    for note_path in sorted((path.parent / "notes").glob("*.md")):
        words = re.findall(r"\w+", note_path.read_text(encoding="utf-8").casefold())
        for index in range(len(words) - width + 1):
            windows.setdefault(tuple(words[index:index + width]), set()).add(note_path.stem)
    matches = [{"text": " ".join(words), "note_ids": sorted(note_ids)} for words, note_ids in windows.items() if len(note_ids) > 1]
    return {"status": "ok", "paper_id": args["paper_id"], "minimum_words": width, "matches": matches, "disclaimer": "Matching text is a review signal, not a plagiarism finding."}


def _check_note_analysis(text: str, paper_id: str, corpus_root: str) -> str | None:
    match = re.search(r"^analysis_id: (.+)$", text.split("---", 2)[1] if text.startswith("---") else "", re.MULTILINE)
    if match:
        from shutong_backend import analysis
        record = analysis.get({"paper_id": paper_id, "analysis_id": match[1]}, corpus_root)["analysis"]
        if record["review"]["outcome"] != "pass":
            raise ShutongError("analysis_not_verified", "Analysis-backed notes require a passing analysis review.")
        digest = analysis._digest(record)
        previous = re.search(r"^analysis_review_sha256: (.+)$", text.split("---", 2)[1], re.MULTILINE)
        if previous and previous[1] != digest:
            raise ShutongError("stale_analysis_note", "Analysis changed after this note was verified; create and verify a fresh note.")
        return digest
    return None


def verify_note(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    """Record the Verifier's evidence check for a note before drafting can use it."""
    path = _paper_path(corpus_root, args["paper_id"])
    paper = _read(path)
    note_id = args["note_id"]
    if not _ID.fullmatch(note_id):
        raise ShutongError("invalid_note_id", "Note IDs use lowercase letters, numbers, and hyphens.")
    note_path = path.parent / "notes" / f"{note_id}.md"
    if not note_path.exists():
        raise ShutongError("note_not_found", f"Note not found: {note_id}")
    evidence = args.get("evidence", "").strip()
    if not evidence:
        raise ShutongError("missing_verification_evidence", "Verified notes require a verifier report or source check reference.")
    text = note_path.read_text(encoding="utf-8")
    analysis_digest = _check_note_analysis(text, paper["id"], corpus_root)
    if "verified: false" not in text:
        raise ShutongError("invalid_note", f"Note {note_id} has no verifiable note metadata.")
    analysis_header = f"analysis_review_sha256: {analysis_digest}\n" if analysis_digest else ""
    note_path.write_text(text.replace("verified: false", f"{analysis_header}verified: true\nverification: {evidence}", 1), encoding="utf-8")
    return {"status": "ok", "paper_id": paper["id"], "note_id": note_id}


def add_claim(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    """Create a draftable assertion only from already verified paper notes."""
    path = _paper_path(corpus_root, args["paper_id"])
    paper = _read(path)
    claim_id = args.get("claim_id") or f"claim-{len(list(path.parent.joinpath('claims').glob('*.json'))) + 1}"
    if not _ID.fullmatch(claim_id):
        raise ShutongError("invalid_claim_id", "Claim IDs use lowercase letters, numbers, and hyphens.")
    note_ids = args.get("note_ids", [])
    if not isinstance(note_ids, list) or not note_ids:
        raise ShutongError("missing_claim_evidence", "Claims require one or more verified note IDs.")
    for note_id in note_ids:
        if not isinstance(note_id, str) or not _ID.fullmatch(note_id):
            raise ShutongError("invalid_note_id", "Invalid claim note ID.")
        note_path = path.parent / "notes" / f"{note_id}.md"
        if not note_path.exists() or "verified: true" not in note_path.read_text(encoding="utf-8"):
            raise ShutongError("note_not_verified", f"Claim evidence is not a verified note: {note_id}")
        _check_note_analysis(note_path.read_text(encoding="utf-8"), paper["id"], corpus_root)
    claim = {"id": claim_id, "text": args.get("text", ""), "note_ids": note_ids, "verified": False}
    (path.parent / "claims" / f"{claim_id}.json").write_text(json.dumps(claim, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "ok", "paper_id": paper["id"], "claim_id": claim_id}


def verify_claim(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    """Record the Verifier's claim-evidence alignment report."""
    path = _paper_path(corpus_root, args["paper_id"])
    paper = _read(path)
    claim_id = args["claim_id"]
    if not _ID.fullmatch(claim_id):
        raise ShutongError("invalid_claim_id", "Claim IDs use lowercase letters, numbers, and hyphens.")
    claim_path = path.parent / "claims" / f"{claim_id}.json"
    if not claim_path.exists():
        raise ShutongError("claim_not_found", f"Claim not found: {claim_id}")
    evidence = args.get("evidence", "").strip()
    if not evidence:
        raise ShutongError("missing_verification_evidence", "Verified claims require a verifier report or evidence reference.")
    claim = json.loads(claim_path.read_text(encoding="utf-8"))
    claim["verified"] = True
    claim["verification"] = evidence
    claim_path.write_text(json.dumps(claim, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "ok", "paper_id": paper["id"], "claim_id": claim_id}


def draft_context(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    """Return only verified claim material after the scholar explicitly asks for a draft."""
    report = audit(args, corpus_root)
    if report["status"] != "ok":
        return {"status": "needs_evidence", "paper_id": report.get("paper_id"), "missing": report.get("missing", [])}
    if not args.get("draft_requested"):
        return {"status": "needs_draft_request", "paper_id": report["paper_id"], "message": "Ask explicitly for a draft after reviewing the verified notes and claims."}
    path = _paper_path(corpus_root, report["paper_id"])
    claims = []
    for claim_path in sorted((path.parent / "claims").glob("*.json")):
        claim = json.loads(claim_path.read_text(encoding="utf-8"))
        if claim.get("verified"):
            claims.append(claim)
    return {"status": "ready", "paper_id": report["paper_id"], "title": _read(path)["title"], "claims": claims}


def export_docx(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    """Export a scholar-approved Markdown draft to a small, local DOCX file."""
    context = draft_context({"paper_id": args["paper_id"], "draft_requested": args.get("draft_requested", False)}, corpus_root)
    if context["status"] != "ready":
        return context
    draft = args.get("draft", "")
    if not isinstance(draft, str) or not draft.strip():
        raise ShutongError("empty_draft", "DOCX export requires non-empty draft Markdown.")
    filename = args.get("filename", "draft")
    if not _ID.fullmatch(filename):
        raise ShutongError("invalid_draft_filename", "Draft filenames use lowercase letters, numbers, and hyphens.")
    paragraphs = "".join(f"<w:p><w:r><w:t xml:space=\"preserve\">{escape(line)}</w:t></w:r></w:p>" for line in draft.splitlines() if line.strip())
    document = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{paragraphs}<w:sectPr/></w:body></w:document>'
    path = _paper_path(corpus_root, args["paper_id"]).parent / "drafts" / f"{filename}.docx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr("word/document.xml", document)
    return {"status": "ok", "paper_id": context["paper_id"], "path": str(path), "claim_count": len(context["claims"])}


def record_verifier_report(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    """Keep a local, reviewable verifier report; no report is silently discarded."""
    path = _paper_path(corpus_root, args["paper_id"])
    paper = _read(path)
    outcome = args.get("outcome")
    if outcome not in {"pass", "fail", "uncertain"}:
        raise ShutongError("invalid_verifier_outcome", "Verifier outcome must be pass, fail, or uncertain.")
    report_id = args.get("report_id") or f"verifier-{len(list(path.parent.joinpath('audits').glob('verifier-*.json'))) + 1}"
    if not _ID.fullmatch(report_id):
        raise ShutongError("invalid_report_id", "Report IDs use lowercase letters, numbers, and hyphens.")
    report = {"id": report_id, "outcome": outcome, "scope": args.get("scope", "paper"), "evidence": args.get("evidence", ""), "defect": args.get("defect", ""), "residual_risk": args.get("residual_risk", "")}
    report_path = path.parent / "audits" / f"{report_id}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "ok", "paper_id": paper["id"], "report_id": report_id, "outcome": outcome}


def override_verifier_report(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    """Append a scholar's documented override without deleting the underlying report."""
    path = _paper_path(corpus_root, args["paper_id"])
    _read(path)
    report_id = args["report_id"]
    report_path = path.parent / "audits" / f"{report_id}.json"
    if not report_path.exists():
        raise ShutongError("report_not_found", f"Verifier report not found: {report_id}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("outcome") == "pass":
        raise ShutongError("override_not_needed", "Only fail or uncertain verifier reports can be overridden.")
    reason = args.get("reason", "").strip()
    if not reason:
        raise ShutongError("missing_override_reason", "Scholar overrides require a reason and visible residual risk.")
    override = {"report_id": report_id, "reason": reason, "residual_risk": args.get("residual_risk", report.get("residual_risk", ""))}
    with (path.parent / "audits" / "overrides.jsonl").open("a", encoding="utf-8") as file:
        file.write(json.dumps(override, ensure_ascii=False) + "\n")
    return {"status": "ok", "paper_id": args["paper_id"], "report_id": report_id, "override": override}


def use(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    paper = _read(_paper_path(corpus_root, args["paper_id"]))
    if paper.get("project_id") and not args.get("confirmed"):
        raise ShutongError("workspace_switch_needs_confirmation", "Activate a project work through the Workspace Planner after the scholar confirms the switch.")
    path = project_root(corpus_root) / ".shutong" / "active-paper"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{paper['id']}\n", encoding="utf-8")
    return {"status": "ok", "paper_id": paper["id"]}


def status(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    paper_id = args.get("paper_id") or active_paper_id(corpus_root)
    if not paper_id:
        return {"status": "no_active_paper"}
    return {"status": "ok", "paper": _read(_paper_path(corpus_root, paper_id)), "active": paper_id == active_paper_id(corpus_root)}


def allowed_source_ids(paper_id: str, corpus_root: str) -> set[str]:
    path = _paper_path(corpus_root, paper_id)
    _, source_paper = _source_paper(path, _read(path), corpus_root)
    return {item["source_id"] for item in source_paper["sources"]}


def audit(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    paper = status(args, corpus_root)
    if paper["status"] != "ok":
        return paper
    manifest = paper["paper"]
    _, source_manifest = _source_paper(_paper_path(corpus_root, manifest["id"]), manifest, corpus_root)
    counts = {role: sum(1 for item in source_manifest["sources"] if item["role"] == role and item.get("ingested")) for role in _ROLES}
    policy = manifest["policy"]
    missing = []
    for role, key in (("primary", "minimum_primary"), ("secondary", "minimum_secondary")):
        if counts[role] < policy[key]:
            missing.append({"role": role, "required": policy[key], "actual": counts[role]})
    if source_manifest.get("bibliography", {}).get("status") != "approved":
        missing.append({"stage": "bibliography", "required": "approved", "actual": source_manifest.get("bibliography", {}).get("status", "missing")})
    if not any(item.get("ingested") for item in source_manifest["sources"]):
        missing.append({"stage": "ingestion", "required": "at least one ingested source", "actual": 0})
    notes = list(_paper_path(corpus_root, manifest["id"]).parent.joinpath("notes").glob("*.md"))
    for note in notes:
        try:
            _check_note_analysis(note.read_text(encoding="utf-8"), manifest["id"], corpus_root)
        except ShutongError as exc:
            missing.append({"stage": "analysis", "note_id": note.stem, "required": "current passing analysis review", "actual": exc.error_code})
    verified_notes = sum("verified: true" in note.read_text(encoding="utf-8") for note in notes)
    if not verified_notes:
        missing.append({"stage": "notes", "required": "at least one verified note", "actual": 0})
    claims = list(_paper_path(corpus_root, manifest["id"]).parent.joinpath("claims").glob("*.json"))
    verified_claims = sum(json.loads(claim.read_text(encoding="utf-8")).get("verified") is True for claim in claims)
    if not verified_claims:
        missing.append({"stage": "claims", "required": "at least one verified claim", "actual": 0})
    return {"status": "ok" if not missing else "incomplete", "paper_id": manifest["id"], "source_counts": counts, "missing": missing}
