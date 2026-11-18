"""Research tools — search and chat over the local corpus."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import Any

from shutong_backend import papers
from shutong_backend.tools.errors import ShutongError

# Regex search is a local availability boundary: the pattern, the scanned text,
# the number of returned matches and the returned byte volume are all bounded.
MAX_PATTERN_LENGTH = 512
MAX_TARGET_CHARS = 20_000
MAX_MATCH_TEXT_CHARS = 500
MAX_MATCHES = 100
MAX_TOTAL_BYTES = 64_000
REGEX_TIME_BUDGET_SECONDS = 2.0

_UNBOUNDED = "unbounded"
_BOUNDED = "bounded"


async def search(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    from shutong_backend.agents.chat import SearchPipeline
    pipeline = SearchPipeline(corpus_root=corpus_root)
    paper_id = papers.resolve_paper_id(args, corpus_root)
    allowed = papers.allowed_source_ids(paper_id, corpus_root) if paper_id else None
    result = await asyncio.to_thread(pipeline.search, args["query"], args.get("top_k", 20), allowed_source_ids=allowed)
    if paper_id:
        result["paper_id"] = paper_id
    return result


async def search_passages(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    """Share the SQLite passage implementation with the TypeScript host."""
    executable = os.environ.get("SHUTONG_MCP_BIN", "shutong-mcp")
    try:
        process = await asyncio.create_subprocess_exec(
            executable, "search-json", stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            env={**os.environ, "SHUTONG_CORPUS_ROOT": corpus_root},
        )
    except OSError as exc:
        raise ShutongError("retrieval_unavailable", "Install shutong-mcp or set SHUTONG_MCP_BIN.") from exc
    try:
        stdout, _ = await asyncio.wait_for(
            process.communicate(json.dumps({**args, "mode": "passages"}).encode()), timeout=330,
        )
        return json.loads(stdout)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise ShutongError("retrieval_timeout", "Passage search exceeded its time budget.") from exc
    except (ValueError, UnicodeError) as exc:
        raise ShutongError("retrieval_failed", "The SQLite search process returned an invalid response.") from exc
    except asyncio.CancelledError:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise


async def chat(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    if papers.resolve_paper_id(args, corpus_root):
        from shutong_backend.tools.errors import ShutongError
        raise ShutongError("paper_scope_required", "The legacy chat pipeline cannot enforce paper source membership.", "Use shutong_search while a paper is active.")
    from shutong_backend.agents.chat import ChatPipeline
    from shutong_backend.rpc_server import _llm_model
    pipeline = ChatPipeline(corpus_root=corpus_root, llm_model=_llm_model())
    return await asyncio.to_thread(pipeline.chat, args["query"])


def _quantifier_at(pattern: str, index: int) -> tuple[str, int] | None:
    """Return (kind, next_index) for a quantifier starting at ``index``."""
    if index >= len(pattern):
        return None
    char = pattern[index]
    if char in "*+":
        end = index + 1
    elif char == "?":
        return (_BOUNDED, index + 1)
    elif char == "{":
        close = pattern.find("}", index)
        body = pattern[index + 1:close] if close != -1 else ""
        if close == -1 or not re.fullmatch(r"\d*(,\d*)?", body):
            return None
        end = close + 1
        upper = body.split(",", 1)[1] if "," in body else body
        kind = _UNBOUNDED if "," in body and not upper else _BOUNDED
        return (kind, end)
    else:
        return None
    # Lazy (``+?``) and possessive (``++``) suffixes do not change the kind.
    if end < len(pattern) and pattern[end] in "?+":
        end += 1
    return (_UNBOUNDED, end)


def _skip_group_prefix(pattern: str, start: int) -> int:
    """Return the index after the opening group prefix at ``start`` (a ``(`` )."""
    index = start + 1
    if index >= len(pattern) or pattern[index] != "?":
        return index
    index += 1
    if index >= len(pattern):
        return index
    marker = pattern[index]
    if marker in ":=!>":
        return index + 1
    if marker in "<=" and index + 1 < len(pattern) and pattern[index + 1] == "=":
        return index + 2
    if marker == "<" and index + 1 < len(pattern) and pattern[index + 1] == "!":
        return index + 2
    if marker in "P<":
        close = pattern.find(">", index)
        return close + 1 if close != -1 else len(pattern)
    if marker == "#":
        close = pattern.find(")", index)
        return close if close != -1 else len(pattern)
    return index


def unsafe_pattern_reason(pattern: str) -> str | None:
    """Conservatively reject constructs prone to catastrophic backtracking.

    The scan rejects a group that is quantified without an upper bound when its
    body already contains a quantifier (``(a+)+``) or an alternation
    (``(a|aa)+``). Both shapes can backtrack exponentially in the stdlib
    engine, which no timeout can interrupt once a single ``search`` call starts.
    """
    stack: list[dict[str, bool]] = []
    index = 0
    in_class = False
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            nxt = pattern[index + 1] if index + 1 < len(pattern) else ""
            if nxt in "123456789":
                return "backreference"
            index += 2
            continue
        if in_class:
            if char == "]":
                in_class = False
            index += 1
            continue
        if char == "[":
            in_class = True
            index += 1
            continue
        if char == "(":
            if pattern.startswith("(?P=", index):
                return "backreference"
            stack.append({"quantified": False, "alternation": False})
            index = _skip_group_prefix(pattern, index)
            continue
        if char == "|":
            if stack:
                stack[-1]["alternation"] = True
            index += 1
            continue
        if char == ")":
            group = stack.pop() if stack else None
            index += 1
            quantifier = _quantifier_at(pattern, index)
            if quantifier is None:
                continue
            kind, index = quantifier
            if group is not None and kind == _UNBOUNDED:
                if group["quantified"]:
                    return "nested_quantifier"
                if group["alternation"]:
                    return "ambiguous_alternation"
            if group is not None and stack:
                # The parent body now contains a quantifier of its own.
                stack[-1]["quantified"] = True
            continue
        if char in "*+?" or char == "{":
            quantifier = _quantifier_at(pattern, index)
            if quantifier is not None:
                _, index = quantifier
                if stack:
                    stack[-1]["quantified"] = True
                continue
        index += 1
    return None


def compile_bounded_pattern(pattern: str) -> re.Pattern[str]:
    """Validate, vet and compile a caller-supplied regex pattern."""
    if not isinstance(pattern, str) or not pattern.strip():
        raise ShutongError("invalid_pattern", "Regex search requires a non-empty pattern.")
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise ShutongError(
            "pattern_too_long",
            f"Regex patterns are limited to {MAX_PATTERN_LENGTH} characters; received {len(pattern)}.",
            "Narrow the pattern before searching.",
        )
    reason = unsafe_pattern_reason(pattern)
    if reason:
        raise ShutongError(
            "unsafe_pattern",
            f"Regex rejected ({reason}): nested or ambiguous quantifiers can hang the search.",
            "Use a linear pattern, or search for a literal substring instead.",
        )
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise ShutongError("invalid_pattern", f"Invalid regular expression: {exc.msg}") from exc


def _snippet(text: str) -> str:
    return text[:MAX_MATCH_TEXT_CHARS]


def _regex_search_sync(
    args: dict[str, Any],
    corpus_root: str,
    budget_seconds: float = REGEX_TIME_BUDGET_SECONDS,
) -> dict[str, Any]:
    from shutong_backend.agents.corpus_loader import CorpusLoader

    pattern = compile_bounded_pattern(args["pattern"])

    loader = CorpusLoader(corpus_root)
    loader.load()
    paper_id = papers.resolve_paper_id(args, corpus_root)
    allowed = papers.allowed_source_ids(paper_id, corpus_root) if paper_id else None
    field = args.get("field", "text")
    # The budget covers matching only; loading the corpus is not the risk here.
    deadline = time.monotonic() + budget_seconds

    matches: list[dict[str, Any]] = []
    total_bytes = 0
    truncated = False
    timed_out = False

    def exhausted() -> bool:
        return len(matches) >= MAX_MATCHES or total_bytes >= MAX_TOTAL_BYTES

    if field == "text":
        for node in loader.all_nodes:
            if time.monotonic() > deadline:
                timed_out = True
                break
            if allowed is not None and node.get("source_id") not in allowed:
                continue
            text = str(node.get("text", ""))[:MAX_TARGET_CHARS]
            if not pattern.search(text):
                continue
            snippet = _snippet(text)
            if exhausted():
                truncated = True
                break
            matches.append({
                "source_id": node.get("source_id", ""),
                "node_id": node.get("node_id", ""),
                "text": snippet,
            })
            total_bytes += len(snippet.encode("utf-8"))
            if exhausted():
                truncated = True
                break
    else:
        for source in loader.sources:
            if time.monotonic() > deadline:
                timed_out = True
                break
            if allowed is not None and source.get("source_id") not in allowed:
                continue
            csl = source.get("csl", {})
            value = ""
            if field == "title":
                value = csl.get("title", "")
            elif field == "author":
                authors = csl.get("author") or []
                if authors:
                    first = authors[0]
                    value = first.get("family") or first.get("literal") or ""
            elif field == "year":
                issued = csl.get("issued", {}).get("date-parts", [])
                if issued and issued[0]:
                    value = str(issued[0][0])
            value = str(value)[:MAX_TARGET_CHARS]
            if not pattern.search(value):
                continue
            snippet = _snippet(value)
            if exhausted():
                truncated = True
                break
            matches.append({"source_id": source.get("source_id", ""), "value": snippet})
            total_bytes += len(snippet.encode("utf-8"))
            if exhausted():
                truncated = True
                break

    result: dict[str, Any] = {
        "status": "ok",
        "matches": matches,
        "match_count": len(matches),
        "truncated": truncated,
        "limits": {
            "max_matches": MAX_MATCHES,
            "max_bytes": MAX_TOTAL_BYTES,
            "max_target_chars": MAX_TARGET_CHARS,
            "max_pattern_length": MAX_PATTERN_LENGTH,
        },
    }
    if timed_out:
        result["timed_out"] = True
        result["truncated"] = True
    if paper_id:
        result["paper_id"] = paper_id
    return result


async def regex_search(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    # Matching never runs on the MCP event loop; the pattern is vetted before
    # it is compiled so a single call cannot start catastrophic backtracking.
    return await asyncio.to_thread(_regex_search_sync, args, corpus_root)
