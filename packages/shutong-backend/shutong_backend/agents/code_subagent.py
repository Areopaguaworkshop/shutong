"""Code Subagent — handles code-related instructions by selecting and executing code tools.

Inspects user intent, selects appropriate code tools, executes them, and returns
a structured result with changes_made, files_modified, and shell_output.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from shutong_backend.tools.code import HANDLERS as CODE_TOOL_HANDLERS

logger = logging.getLogger(__name__)

# ── Intent detection ───────────────────────────────────────────────────

_CODE_INTENT_PATTERNS = re.compile(
    r"\b(edit|fix|refactor|create|write|update|modify|delete|remove|"
    r"run|execute|build|test|install|move|rename|search|find|grep|glob|"
    r"cat|head|tail|ls|list|read|show|print|replace|patch|debug|compile)\b",
    re.IGNORECASE,
)


def detect_code_intent(text: str) -> bool:
    """Return True if the text appears to be a code-related instruction."""
    return bool(_CODE_INTENT_PATTERNS.search(text))


# ── Tool selection ─────────────────────────────────────────────────────

_TOOL_SELECTION_PROMPT = """You are a code tool selector. Given a user instruction, select the most appropriate tools and their parameters.

Available tools:
- shutong_file_read: Read file contents. Params: path, start_line, end_line
- shutong_file_write: Write/create file. Params: path, content
- shutong_file_edit: Edit file by exact string replacement. Params: path, old_string, new_string, replace_all
- shutong_file_list: List directory contents. Params: path
- shutong_bash: Execute shell command. Params: command, timeout, workdir
- shutong_grep: Search file contents by regex. Params: pattern, path, case_insensitive, max_results
- shutong_glob: Find files by name pattern. Params: pattern, path, max_results

Respond with a JSON array of tool calls, each with "tool" and "params" keys.
Example: [{"tool": "shutong_file_read", "params": {"path": "README.md"}}]

User instruction: {instruction}
Project root: {root}

Respond with ONLY the JSON array, no other text."""


def _select_tools_rule_based(instruction: str, root: str) -> list[dict[str, Any]]:
    """Rule-based tool selection fallback when LLM is unavailable."""
    tools: list[dict[str, Any]] = []
    lower = instruction.lower()

    # Extract file paths mentioned in the instruction
    mentioned_paths = re.findall(r'[\w./\-]+\.\w{1,10}', instruction)

    # Search/grep patterns
    if any(kw in lower for kw in ("search", "find", "grep", "where is")):
        # Extract search term (text after the keyword)
        for kw in ("search", "find", "grep for", "where is"):
            idx = lower.find(kw)
            if idx >= 0:
                term = instruction[idx + len(kw):].strip().strip('"\'')
                if term:
                    tools.append({"tool": "shutong_grep", "params": {"pattern": term, "path": "."}})
                    break

    # Glob patterns
    if any(kw in lower for kw in ("list files", "glob", "find files")):
        pattern_match = re.search(r'[\w*?.[\]]+\.\w+', instruction)
        tools.append({"tool": "shutong_glob", "params": {"pattern": pattern_match.group() if pattern_match else "*.py", "path": "."}})

    # File reads
    for p in mentioned_paths:
        if any(kw in lower for kw in ("read", "show", "cat", "display", "view", "open")):
            tools.append({"tool": "shutong_file_read", "params": {"path": p}})

    # File edits/writes
    if any(kw in lower for kw in ("edit", "fix", "update", "modify", "change", "replace", "patch")):
        for p in mentioned_paths:
            tools.append({"tool": "shutong_file_read", "params": {"path": p}})

    if any(kw in lower for kw in ("create", "write", "new file")):
        for p in mentioned_paths:
            tools.append({"tool": "shutong_file_write", "params": {"path": p, "content": ""}})

    # Shell commands
    if any(kw in lower for kw in ("run", "execute", "build", "test", "install", "compile", "bash")):
        tools.append({"tool": "shutong_bash", "params": {"command": instruction}})

    # Directory listing
    if any(kw in lower for kw in ("ls", "list", "dir")):
        tools.append({"tool": "shutong_file_list", "params": {"path": "."}})

    # Default: at least read the file if a path is mentioned
    if not tools and mentioned_paths:
        tools.append({"tool": "shutong_file_read", "params": {"path": mentioned_paths[0]}})

    # Absolute fallback: list the directory
    if not tools:
        tools.append({"tool": "shutong_file_list", "params": {"path": "."}})

    return tools


# ── Agent ───────────────────────────────────────────────────────────────


class CodeSubagentAgent:
    """Code subagent that handles code-related instructions."""

    def __init__(self, corpus_root: str = "corpus", llm_model: str = "ollama/deepseek-v4-pro:cloud") -> None:
        self.corpus_root = corpus_root
        self.llm_model = llm_model

    def run(self, instruction: str, code_root: str | None = None) -> dict[str, Any]:
        """Execute a code instruction and return structured result.

        Returns dict with keys:
            status: "ok" or "error"
            result: summary of what was done
            changes_made: list of change descriptions
            files_modified: list of file paths that were modified
            shell_output: captured shell output (if any)
        """
        root = code_root or os.environ.get("SHUTONG_CODE_ROOT") or self.corpus_root

        # Select tools
        tool_calls = self._select_tools(instruction, root)

        changes_made: list[str] = []
        files_modified: list[str] = []
        shell_output: str = ""
        all_results: list[dict[str, Any]] = []

        for call in tool_calls:
            tool_name = call["tool"]
            params = call.get("params", {})
            params.setdefault("code_root", root)

            handler = CODE_TOOL_HANDLERS.get(tool_name)
            if not handler:
                changes_made.append(f"Unknown tool: {tool_name}")
                continue

            try:
                import asyncio
                result = asyncio.get_event_loop().run_until_complete(
                    handler(params, self.corpus_root)
                ) if asyncio.get_event_loop().is_running() else asyncio.run(
                    handler(params, self.corpus_root)
                )
            except RuntimeError:
                import asyncio
                result = asyncio.run(handler(params, self.corpus_root))

            all_results.append({"tool": tool_name, "result": result})

            if result.get("status") == "ok":
                if "write" in tool_name or "edit" in tool_name:
                    path = result.get("path", params.get("path", ""))
                    files_modified.append(path)
                    changes_made.append(f"{tool_name}: {path}")
                elif "bash" in tool_name:
                    shell_output += result.get("stdout", "")
                    if result.get("stderr"):
                        shell_output += "\n" + result.get("stderr", "")
                    changes_made.append(f"bash: exit={result.get('exit_code', '?')}")
                elif "read" in tool_name or "list" in tool_name or "grep" in tool_name or "glob" in tool_name:
                    changes_made.append(f"{tool_name}: {self._summarize_result(result)}")
            else:
                changes_made.append(f"{tool_name} error: {result.get('message', 'unknown')}")

        return {
            "status": "ok" if files_modified or shell_output else "ok",
            "instruction": instruction,
            "result": "\n".join(changes_made),
            "changes_made": changes_made,
            "files_modified": files_modified,
            "shell_output": shell_output[:5000],
            "tool_results": all_results,
        }

    def _select_tools(self, instruction: str, root: str) -> list[dict[str, Any]]:
        """Select tools for the instruction, falling back to rule-based selection."""
        # Try LLM-based selection first
        try:
            return self._select_tools_llm(instruction, root)
        except Exception as exc:
            logger.debug("LLM tool selection failed, using rule-based: %s", exc)
            return _select_tools_rule_based(instruction, root)

    def _select_tools_llm(self, instruction: str, root: str) -> list[dict[str, Any]]:
        """Use LLM to select appropriate code tools."""
        from shutong_backend.llm import get_llm

        llm = get_llm(self.llm_model)
        prompt = _TOOL_SELECTION_PROMPT.format(instruction=instruction, root=root)
        model = getattr(llm, "_default_model", "")
        response = llm.invoke(prompt, model=model)

        text = response.content if hasattr(response, "content") else str(response)
        # Extract JSON from response
        json_match = re.search(r'\[.*\]', text, re.DOTALL)
        if not json_match:
            raise ValueError(f"No JSON array found in LLM response: {text[:200]}")

        tool_calls = json.loads(json_match.group())
        if not isinstance(tool_calls, list):
            raise ValueError("LLM did not return a JSON array")

        # Validate tool names
        valid_calls = []
        for call in tool_calls:
            tool_name = call.get("tool", "")
            if tool_name in CODE_TOOL_HANDLERS:
                valid_calls.append(call)

        return valid_calls or _select_tools_rule_based(instruction, root)

    @staticmethod
    def _summarize_result(result: dict[str, Any]) -> str:
        """Create a brief summary of a tool result."""
        if "total_lines" in result:
            return f"read {result.get('total_lines', '?')} lines"
        if "entries" in result:
            return f"listed {len(result['entries'])} entries"
        if "matches" in result:
            return f"found {len(result['matches'])} matches"
        if "files" in result:
            return f"found {len(result['files'])} files"
        return "ok"