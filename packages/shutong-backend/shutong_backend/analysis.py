"""Bounded, paper-scoped text analysis with source spans and local run records."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from uuid import uuid4

from shutong_backend import papers
from shutong_backend.agents.corpus_loader import CorpusLoader
from shutong_backend.tools.errors import ShutongError
from shutong_backend.tools.verify import _verify_document

MODES = ("concordance", "collocations", "contextual_sentiment", "quotation", "text_reuse")
LABELS = ("favorable", "unfavorable", "neutral", "mixed", "uncertain")
VERSION = "text-analysis-v1"

_PROPERTIES = {
    "action": {"enum": ["run", "get", "annotate", "review"]}, "paper_id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{0,62}$"},
    "mode": {"enum": list(MODES)}, "language": {"enum": ["en", "zh"]}, "question": {"type": "string"},
    "source_ids": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1, "maxItems": 50, "uniqueItems": True},
    "query": {"type": "string"}, "rubric": {"type": "string"}, "window": {"type": "integer", "minimum": 1, "maximum": 20},
    "minimum_tokens": {"type": "integer", "minimum": 4, "maximum": 30}, "context": {"type": "integer", "minimum": 20, "maximum": 1000},
    "limit": {"type": "integer", "minimum": 1, "maximum": 200}, "analysis_id": {"type": "string", "pattern": "^analysis-[a-f0-9]{32}$"},
    "record_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"}, "model_id": {"type": "string"},
    "annotations": {"type": "array", "items": {"type": "object"}}, "outcome": {"enum": ["pass", "fail", "uncertain"]},
    "evidence": {"type": "string"}, "reviewer": {"type": "string"},
}
_REQUIRED = {"run": ["mode", "language", "question", "source_ids"], "get": ["analysis_id"],
             "annotate": ["analysis_id", "record_sha256", "model_id", "annotations"],
             "review": ["analysis_id", "record_sha256", "outcome", "evidence", "reviewer"]}
SCHEMA = {"type": "object", "properties": _PROPERTIES, "additionalProperties": False, "required": ["action", "paper_id"],
          "oneOf": [{"properties": {"action": {"const": action}}, "required": fields} for action, fields in _REQUIRED.items()]}


def dispatch(args, corpus_root):
    from jsonschema import validate, ValidationError
    try:
        validate(args, SCHEMA)
    except ValidationError as exc:
        raise ShutongError("invalid_input", exc.message) from exc
    return {"run": run, "get": get, "annotate": annotate, "review": review}[args["action"]](args, corpus_root)


def _text(args, key):
    value = args.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > 10000:
        raise ShutongError("invalid_input", f"{key} must be non-empty text of at most 10000 characters.")
    return value


def _integer(args, key, default, low, high):
    value = args.get(key, default)
    if type(value) is not int or not low <= value <= high:
        raise ShutongError("invalid_input", f"{key} must be an integer from {low} to {high}.")
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _tokens(text):
    """Unicode words and individual Han characters, retaining original offsets."""
    # ponytail: Han character units, not Chinese word segmentation; add a versioned segmenter when required.
    tokens, start = [], None
    for index, char in enumerate(text + " "):
        han = "\u3400" <= char <= "\u4dbf" or "\u4e00" <= char <= "\u9fff" or "\U00020000" <= char <= "\U000323af"
        word = unicodedata.category(char)[0] in "LMN" or (char in "'’" and start is not None and index + 1 < len(text) and text[index + 1].isalpha())
        if start is not None and (han or not word):
            tokens.append((unicodedata.normalize("NFC", text[start:index]).casefold(), start, index))
            start = None
        if han:
            tokens.append((char, index, index + 1))
        elif word and start is None:
            start = index
    return tokens


def _scope(paper_id, source_ids, corpus_root):
    if not isinstance(paper_id, str) or not papers._ID.fullmatch(paper_id):
        raise ShutongError("invalid_input", "A valid explicit paper_id is required.")
    path = papers._paper_path(corpus_root, paper_id)
    _, manifest = papers._source_paper(path, papers._read(path), corpus_root)
    if manifest.get("bibliography", {}).get("status") != "approved":
        raise ShutongError("bibliography_not_approved", "Approve the source bibliography before analysis.")
    if not isinstance(source_ids, list) or not 1 <= len(source_ids) <= 50 or any(not isinstance(s, str) or not s for s in source_ids) or len(set(source_ids)) != len(source_ids):
        raise ShutongError("invalid_input", "source_ids must contain 1–50 unique source IDs.")
    approved = {entry["id"] for entry in manifest["bibliography"]["entries"]}
    ingested = {s["source_id"] for s in manifest["sources"] if s.get("ingested")}
    if not set(source_ids) <= approved & ingested:
        raise ShutongError("source_not_ingested", "Analysis requires approved, ingested sources belonging to this paper.")
    loader = CorpusLoader(corpus_root)
    loader.load()
    nodes, sources = [], []
    for source_id in sorted(source_ids):
        candidates = [s for s in loader.sources if s["source_id"] == source_id]
        selected = loader.get_nodes_by_source(source_id)
        merkle = loader.merkle_registry.get(source_id, {})
        if len(candidates) != 1 or not selected or not merkle.get("root") or not merkle.get("levels"):
            raise ShutongError("unverified_source", f"Missing or ambiguous corpus evidence: {source_id}")
        if _verify_document(loader, candidates[0])["status"] != "pass":
            raise ShutongError("unverified_source", f"Source integrity failed: {source_id}")
        ids = [n.get("node_id") for n in selected]
        if any(not isinstance(n, str) or not n for n in ids) or len(set(ids)) != len(ids):
            raise ShutongError("invalid_locator", f"Source needs unique node IDs: {source_id}")
        nodes.extend(selected)
        sources.append({"source_id": source_id, "merkle_root": merkle["root"], "snapshot_sha256": _digest(selected), "csl": candidates[0]["csl"]})
    if len(nodes) > 5000 or sum(len(n["text"]) for n in nodes) > 2_000_000:
        raise ShutongError("analysis_too_large", "Narrow source selection to 5000 nodes and 2 million characters per run.")
    return nodes, sources


def _span(node, start, end):
    return {"source_id": node["source_id"], "node_id": node["node_id"], "node_sha256": node["sha256"],
            "page": node.get("page"), "section_path": node.get("section_path"),
            "start": start, "end": end, "text": node["text"][start:end]}


def _contexts(nodes, query, radius, limit, exact=False):
    contexts, count = [], 0
    wanted = [t[0] for t in _tokens(query)]
    if not exact and not wanted:
        raise ShutongError("invalid_input", "query must contain a word or Han character.")
    for node in nodes:
        text = node["text"]
        if exact:
            spans = ((m.start(), m.start() + len(query)) for m in re.finditer(f"(?={re.escape(query)})", text))
        else:
            tokens = _tokens(text)
            spans = ((tokens[i][1], tokens[i + len(wanted) - 1][2]) for i in range(len(tokens) - len(wanted) + 1) if [t[0] for t in tokens[i:i + len(wanted)]] == wanted)
        for start, end in spans:
            count += 1
            if len(contexts) < limit:
                contexts.append({**_span(node, start, end), "left": text[max(0, start - radius):start], "right": text[end:end + radius]})
    return {"contexts": contexts, "total_occurrences": count, "returned": len(contexts), "truncated": count > len(contexts)}


def _collocations(nodes, query, window, limit):
    wanted = [t[0] for t in _tokens(query)]
    if not wanted:
        raise ShutongError("invalid_input", "query must contain a word or Han character.")
    counts, documents, examples = Counter(), defaultdict(set), {}
    occurrences = total_tokens = 0
    for node in nodes:
        tokens = _tokens(node["text"])
        total_tokens += len(tokens)
        for index in range(len(tokens) - len(wanted) + 1):
            if [t[0] for t in tokens[index:index + len(wanted)]] != wanted:
                continue
            occurrences += 1
            positions = list(range(max(0, index - window), index)) + list(range(index + len(wanted), min(len(tokens), index + len(wanted) + window)))
            for position in positions:
                token, start, end = tokens[position]
                counts[token] += 1
                documents[token].add(node["source_id"])
                examples.setdefault(token, {"collocate": _span(node, start, end), "target": _span(node, tokens[index][1], tokens[index + len(wanted) - 1][2])})
    ordered = sorted(counts, key=lambda token: (-counts[token], token))
    return {"target_occurrences": occurrences, "corpus_tokens": total_tokens, "total_collocates": len(ordered), "truncated": len(ordered) > limit,
            "collocates": [{"token": t, "count": counts[t], "document_frequency": len(documents[t]), "example": examples[t]} for t in ordered[:limit]]}


def _reuse(nodes, width, limit):
    windows = defaultdict(list)
    total = 0
    for node in nodes:
        tokens = _tokens(node["text"])
        for i in range(len(tokens) - width + 1):
            total += 1
            if total > 200000:
                raise ShutongError("analysis_too_large", "Exact reuse is limited to 200000 token windows; narrow the source set.")
            key = tuple(t[0] for t in tokens[i:i + width])
            windows[key].append((node, tokens[i][1], tokens[i + width - 1][2]))
    matches, groups = [], 0
    for key in sorted(windows):
        occurrences = windows[key]
        if len({n["source_id"] for n, _, _ in occurrences}) < 2:
            continue
        groups += 1
        if len(matches) < limit:
            matches.append({"tokens": list(key), "occurrences": [_span(n, start, end) for n, start, end in occurrences[:limit]],
                            "total_occurrences": len(occurrences), "occurrences_truncated": len(occurrences) > limit})
    return {"matches": matches, "total_match_groups": groups, "truncated": groups > limit, "windows_checked": total}


def _path(paper_id, analysis_id, corpus_root):
    if not isinstance(paper_id, str) or not papers._ID.fullmatch(paper_id):
        raise ShutongError("invalid_input", "A valid explicit paper_id is required.")
    if not isinstance(analysis_id, str) or not re.fullmatch(r"analysis-[a-f0-9]{32}", analysis_id):
        raise ShutongError("invalid_input", "Invalid analysis_id.")
    paper = papers._paper_path(corpus_root, paper_id)
    papers._read(paper)
    return paper.parent / "analyses" / f"{analysis_id}.json"


def _save(record, corpus_root):
    path = _path(record["paper_id"], record["analysis_id"], corpus_root)
    path.parent.mkdir(exist_ok=True)
    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _response(record):
    return {"status": "ok", "analysis": record, "record_sha256": _digest(record)}


def run(args, corpus_root):
    mode = args.get("mode")
    if mode not in MODES or args.get("language") not in {"en", "zh"}:
        raise ShutongError("invalid_input", "Choose a supported analysis mode and language (en or zh).")
    if args.get("library_wide"):
        raise ShutongError("invalid_input", "Analysis requires an explicit paper source set.")
    _text(args, "question")
    limit = _integer(args, "limit", 100, 1, 200)
    radius = _integer(args, "context", 160, 20, 1000)
    window = _integer(args, "window", 5, 1, 20)
    width = _integer(args, "minimum_tokens", 8, 4, 30)
    query = _text(args, "query") if mode != "text_reuse" else ""
    rubric = _text(args, "rubric") if mode == "contextual_sentiment" else None
    if mode == "text_reuse" and len(args.get("source_ids", [])) < 2:
        raise ShutongError("invalid_input", "Source reuse requires at least two source IDs.")
    nodes, sources = _scope(args.get("paper_id"), args.get("source_ids"), corpus_root)
    parameters = {"query": query, "language": args["language"], "window": window, "minimum_tokens": width, "context": radius, "limit": limit, "rubric": rubric}
    if mode == "collocations":
        result = _collocations(nodes, query, window, limit)
    elif mode == "text_reuse":
        result = _reuse(nodes, width, limit)
    else:
        result = _contexts(nodes, query, radius, limit, exact=mode == "quotation")
    record = {"schema_version": 1, "analysis_id": f"analysis-{uuid4().hex}", "paper_id": args["paper_id"], "created_at": _now(),
              "question": args["question"], "mode": mode, "method": VERSION, "tokenizer": "unicode-words-han-characters-v1",
              "parameters": parameters, "sources": sources, "node_count": len(nodes), "results": result, "annotations": [],
              "review": {"outcome": "pending"}, "limitations": [
                  "Matches and windows do not cross corpus node boundaries; Han units are characters, not segmented words.",
                  "Collocations count neighboring tokens per target occurrence, without significance or causal inference.",
                  "Reuse means equal NFC/casefolded token sequences; punctuation is ignored. It is not proof of borrowing or plagiarism.",
                  "Quotation matching is case-sensitive and exact in the ingested text, not a check against the original page image.",
                  "Contextual sentiment is agent interpretation under the supplied rubric; no automatic sentiment scores are computed.",
                  "Merkle checks concern local corpus integrity, not historical authenticity or semantic claim support."]}
    _save(record, corpus_root)
    return _response(record)


def get(args, corpus_root):
    path = _path(args.get("paper_id"), args.get("analysis_id"), corpus_root)
    if not path.exists():
        raise ShutongError("analysis_not_found", "Analysis not found in this paper.")
    record = json.loads(path.read_text(encoding="utf-8"))
    _, sources = _scope(args["paper_id"], [s["source_id"] for s in record["sources"]], corpus_root)
    if sources != record["sources"]:
        raise ShutongError("stale_analysis", "Source text, locations or bibliography changed; rerun the analysis.")
    return _response(record)


def annotate(args, corpus_root):
    response = get(args, corpus_root)
    record = response["analysis"]
    if args.get("record_sha256") != response["record_sha256"]:
        raise ShutongError("stale_analysis", "Read the latest analysis before annotating it.")
    if record["mode"] != "contextual_sentiment":
        raise ShutongError("invalid_input", "Annotations are supported for contextual sentiment only.")
    model_id = _text(args, "model_id")
    annotations = args.get("annotations")
    if not isinstance(annotations, list) or not 1 <= len(annotations) <= len(record["results"]["contexts"]):
        raise ShutongError("invalid_input", "Provide annotations for one or more returned contexts.")
    clean, seen = [], set()
    for item in annotations:
        if not isinstance(item, dict):
            raise ShutongError("invalid_input", "Each annotation must be an object.")
        index = _integer(item, "context_index", -1, 0, len(record["results"]["contexts"]) - 1)
        if index in seen or item.get("label") not in LABELS or item.get("confidence") not in {"known", "probable", "speculative"}:
            raise ShutongError("invalid_input", "Use unique context indices, a supported label and explicit confidence.")
        seen.add(index)
        clean.append({"context_index": index, "label": item["label"], "confidence": item["confidence"],
                      **{key: _text(item, key) for key in ("target", "speaker", "rationale")}})
    record["annotations"] = clean
    record["interpretation"] = {"model_id": model_id, "recorded_at": _now(), "reproducibility": "Model identity is recorded; identical future interpretations are not guaranteed."}
    record["review"] = {"outcome": "pending"}
    _save(record, corpus_root)
    return _response(record)


def review(args, corpus_root):
    response = get(args, corpus_root)
    record = response["analysis"]
    if args.get("record_sha256") != response["record_sha256"]:
        raise ShutongError("stale_analysis", "Review must reference the exact inspected record_sha256.")
    if args.get("outcome") not in {"pass", "fail", "uncertain"}:
        raise ShutongError("invalid_input", "Review outcome must be pass, fail or uncertain.")
    if args["outcome"] == "pass" and record["mode"] == "contextual_sentiment" and not record["annotations"]:
        raise ShutongError("missing_interpretation", "Context retrieval alone cannot verify a sentiment interpretation.")
    record["review"] = {"outcome": args["outcome"], "evidence": _text(args, "evidence"), "reviewer": _text(args, "reviewer"),
                        "recorded_at": _now(), "inspected_sha256": response["record_sha256"]}
    _save(record, corpus_root)
    return _response(record)
