"""Code tools — file read/write/edit, shell execution, and code search.

All file operations are scoped to the project's corpus_root or an explicit
code_root directory to prevent path traversal outside the project.
"""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
from pathlib import Path
from typing import Any


def _resolve_root(args: dict[str, Any], corpus_root: str) -> str:
    """Resolve the code root directory, defaulting to corpus_root."""
    return args.get("code_root") or os.environ.get("SHUTONG_CODE_ROOT") or corpus_root


def _safe_path(path: str, root: str) -> str:
    """Resolve and validate that path stays within root."""
    resolved = os.path.realpath(path)
    root_resolved = os.path.realpath(root)
    if not resolved.startswith(root_resolved + os.sep) and resolved != root_resolved:
        raise ValueError(f"Path escapes code root: {path}")
    return resolved


# ── Tool handlers ──────────────────────────────────────────────────────


async def file_read(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    """Read file contents with optional line range support."""
    root = _resolve_root(args, corpus_root)
    filepath = args.get("path", "")
    if not filepath:
        return {"status": "error", "message": "path is required"}

    try:
        full_path = _safe_path(filepath if os.path.isabs(filepath) else os.path.join(root, filepath), root)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    if not os.path.isfile(full_path):
        return {"status": "error", "message": f"File not found: {filepath}"}

    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        start = max(1, args.get("start_line", 1))
        end = min(len(lines), args.get("end_line", len(lines)))
        selected = lines[start - 1:end]
        return {
            "status": "ok",
            "path": filepath,
            "content": "".join(selected),
            "total_lines": len(lines),
            "start_line": start,
            "end_line": end,
        }
    except Exception as exc:
        return {"status": "error", "message": f"Failed to read file: {exc}"}


async def file_write(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    """Write or create a file with the given contents."""
    root = _resolve_root(args, corpus_root)
    filepath = args.get("path", "")
    content = args.get("content", "")

    if not filepath:
        return {"status": "error", "message": "path is required"}

    try:
        full_path = _safe_path(filepath if os.path.isabs(filepath) else os.path.join(root, filepath), root)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    try:
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"status": "ok", "path": filepath, "bytes_written": len(content.encode("utf-8"))}
    except Exception as exc:
        return {"status": "error", "message": f"Failed to write file: {exc}"}


async def file_edit(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    """Exact-string replacement edit (like OpenCode's edit tool)."""
    root = _resolve_root(args, corpus_root)
    filepath = args.get("path", "")
    old_string = args.get("old_string", "")
    new_string = args.get("new_string", "")

    if not filepath:
        return {"status": "error", "message": "path is required"}
    if not old_string:
        return {"status": "error", "message": "old_string is required"}

    try:
        full_path = _safe_path(filepath if os.path.isabs(filepath) else os.path.join(root, filepath), root)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    if not os.path.isfile(full_path):
        return {"status": "error", "message": f"File not found: {filepath}"}

    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        count = content.count(old_string)
        if count == 0:
            return {"status": "error", "message": f"old_string not found in {filepath}"}
        if count > 1 and not args.get("replace_all", False):
            return {"status": "error", "message": f"old_string found {count} times in {filepath}. Use replace_all=true or provide a more specific string."}

        if args.get("replace_all", False):
            new_content = content.replace(old_string, new_string)
        else:
            new_content = content.replace(old_string, new_string, 1)

        with open(full_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        return {
            "status": "ok",
            "path": filepath,
            "replacements": count if args.get("replace_all", False) else 1,
        }
    except Exception as exc:
        return {"status": "error", "message": f"Failed to edit file: {exc}"}


async def file_list(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    """List directory contents (like ls)."""
    root = _resolve_root(args, corpus_root)
    dirpath = args.get("path", ".")

    try:
        full_path = _safe_path(dirpath if os.path.isabs(dirpath) else os.path.join(root, dirpath), root)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    if not os.path.isdir(full_path):
        return {"status": "error", "message": f"Directory not found: {dirpath}"}

    try:
        entries = []
        for entry in sorted(os.listdir(full_path)):
            entry_path = os.path.join(full_path, entry)
            entries.append({
                "name": entry,
                "type": "directory" if os.path.isdir(entry_path) else "file",
                "size": os.path.getsize(entry_path) if os.path.isfile(entry_path) else 0,
            })
        return {"status": "ok", "path": dirpath, "entries": entries}
    except Exception as exc:
        return {"status": "error", "message": f"Failed to list directory: {exc}"}


async def bash(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    """Execute a shell command with timeout and output capture."""
    command = args.get("command", "")
    if not command:
        return {"status": "error", "message": "command is required"}

    timeout = min(args.get("timeout", 30), 120)
    workdir = args.get("workdir")
    root = _resolve_root(args, corpus_root)
    if workdir:
        try:
            workdir = _safe_path(workdir if os.path.isabs(workdir) else os.path.join(root, workdir), root)
        except ValueError:
            workdir = root
    else:
        workdir = root

    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=workdir,
            env={**os.environ, "SHUTONG_CODE_ROOT": root},
        )
        return {
            "status": "ok" if proc.returncode == 0 else "error",
            "exit_code": proc.returncode,
            "stdout": proc.stdout[:10000],
            "stderr": proc.stderr[:10000],
            "truncated": len(proc.stdout) > 10000 or len(proc.stderr) > 10000,
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": f"Command timed out after {timeout}s"}
    except Exception as exc:
        return {"status": "error", "message": f"Failed to execute command: {exc}"}


async def grep(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    """Search file contents by regex pattern (like grep -rn)."""
    root = _resolve_root(args, corpus_root)
    pattern = args.get("pattern", "")
    search_path = args.get("path", ".")

    if not pattern:
        return {"status": "error", "message": "pattern is required"}

    try:
        full_path = _safe_path(search_path if os.path.isabs(search_path) else os.path.join(root, search_path), root)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    if not os.path.exists(full_path):
        return {"status": "error", "message": f"Path not found: {search_path}"}

    max_results = args.get("max_results", 50)
    case_insensitive = args.get("case_insensitive", True)

    try:
        regex = re.compile(pattern, re.IGNORECASE if case_insensitive else 0)
    except re.error as exc:
        return {"status": "error", "message": f"Invalid regex pattern: {exc}"}

    matches = []
    search_dir = full_path if os.path.isdir(full_path) else os.path.dirname(full_path)

    for dirpath, dirnames, filenames in os.walk(search_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "node_modules"]
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    for line_no, line in enumerate(f, 1):
                        if regex.search(line):
                            rel_path = os.path.relpath(filepath, root)
                            matches.append({
                                "path": rel_path,
                                "line": line_no,
                                "content": line.rstrip()[:200],
                            })
                            if len(matches) >= max_results:
                                return {"status": "ok", "pattern": pattern, "matches": matches, "truncated": True}
            except (UnicodeDecodeError, PermissionError):
                continue

    return {"status": "ok", "pattern": pattern, "matches": matches, "truncated": False}


async def glob(args: dict[str, Any], corpus_root: str) -> dict[str, Any]:
    """Find files by name pattern (like find -name)."""
    root = _resolve_root(args, corpus_root)
    pattern = args.get("pattern", "")
    search_path = args.get("path", ".")

    if not pattern:
        return {"status": "error", "message": "pattern is required"}

    try:
        full_path = _safe_path(search_path if os.path.isabs(search_path) else os.path.join(root, search_path), root)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    if not os.path.isdir(full_path):
        return {"status": "error", "message": f"Directory not found: {search_path}"}

    max_results = args.get("max_results", 100)
    matches = []

    for dirpath, dirnames, filenames in os.walk(full_path):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "node_modules"]
        for filename in filenames:
            if fnmatch.fnmatch(filename, pattern):
                rel_path = os.path.relpath(os.path.join(dirpath, filename), root)
                matches.append(rel_path)
                if len(matches) >= max_results:
                    return {"status": "ok", "pattern": pattern, "files": matches, "truncated": True}

    return {"status": "ok", "pattern": pattern, "files": matches, "truncated": False}


# ── Dispatch table ─────────────────────────────────────────────────────

HANDLERS: dict[str, Any] = {
    "shutong_file_read": file_read,
    "shutong_file_write": file_write,
    "shutong_file_edit": file_edit,
    "shutong_file_list": file_list,
    "shutong_bash": bash,
    "shutong_grep": grep,
    "shutong_glob": glob,
}