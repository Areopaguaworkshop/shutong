"""Permission Manager — per-tool ask/allow/deny permissions.

Controls which code tools require user confirmation before execution.
Default policy: read operations are allowed, write/bash operations require confirmation.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class Permission(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class PermissionRule:
    """A single permission rule matching a tool pattern to a permission level."""

    def __init__(self, tool_pattern: str, permission: Permission) -> None:
        self.tool_pattern = tool_pattern
        self.permission = permission

    def matches(self, tool_name: str) -> bool:
        return fnmatch.fnmatch(tool_name, self.tool_pattern)

    def to_dict(self) -> Dict[str, str]:
        return {"tool_pattern": self.tool_pattern, "permission": self.permission.value}

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "PermissionRule":
        return cls(tool_pattern=data["tool_pattern"], permission=Permission(data["permission"]))


# ── Default permission rules ─────────────────────────────────────────────

DEFAULT_RULES: List[PermissionRule] = [
    # Read-only tools — always allowed
    PermissionRule("shutong_file_read", Permission.ALLOW),
    PermissionRule("shutong_grep", Permission.ALLOW),
    PermissionRule("shutong_glob", Permission.ALLOW),
    PermissionRule("shutong_search", Permission.ALLOW),
    PermissionRule("shutong_file_list", Permission.ALLOW),
    PermissionRule("shutong_corpus_status", Permission.ALLOW),
    PermissionRule("shutong_corpus_tree", Permission.ALLOW),
    PermissionRule("shutong_verify_document", Permission.ALLOW),
    PermissionRule("shutong_verify_all", Permission.ALLOW),
    PermissionRule("shutong_resolve_citation", Permission.ALLOW),
    PermissionRule("shutong_cite_render", Permission.ALLOW),
    PermissionRule("shutong_cite_tree", Permission.ALLOW),
    PermissionRule("shutong_memory_search", Permission.ALLOW),
    # Write tools — require confirmation
    PermissionRule("shutong_file_write", Permission.ASK),
    PermissionRule("shutong_file_edit", Permission.ASK),
    PermissionRule("shutong_bash", Permission.ASK),
    PermissionRule("shutong_ingest", Permission.ASK),
    PermissionRule("shutong_delete_document", Permission.ASK),
    PermissionRule("shutong_memory_save", Permission.ASK),
    # Subagent — ask by default
    PermissionRule("code_subagent", Permission.ASK),
    # Destructive tools — denied by default
    PermissionRule("shutong_delete_*", Permission.DENY),
]


class PermissionManager:
    """Manage per-tool permissions with pattern matching."""

    def __init__(self, config_path: Optional[str] = None) -> None:
        self.rules: List[PermissionRule] = list(DEFAULT_RULES)
        self._config_path = config_path
        if config_path:
            self.load_config(config_path)

    def check(self, tool_name: str) -> Permission:
        """Check the permission level for a given tool name.

        Returns the first matching rule's permission, or ASK if no rule matches.
        """
        for rule in self.rules:
            if rule.matches(tool_name):
                return rule.permission
        # Default: ask for confirmation
        return Permission.ASK

    def set(self, tool_pattern: str, permission: Permission) -> None:
        """Set a permission rule. Updates existing rule if pattern matches."""
        for rule in self.rules:
            if rule.tool_pattern == tool_pattern:
                rule.permission = permission
                return
        self.rules.append(PermissionRule(tool_pattern, permission))

    def remove(self, tool_pattern: str) -> None:
        """Remove a permission rule by pattern."""
        self.rules = [r for r in self.rules if r.tool_pattern != tool_pattern]

    def load_config(self, config_path: str) -> None:
        """Load permission rules from a JSON config file."""
        path = Path(config_path)
        if not path.exists():
            return

        try:
            with open(path) as f:
                data = json.load(f)

            rules_data = data.get("rules", [])
            for rd in rules_data:
                rule = PermissionRule.from_dict(rd)
                # Replace existing rule with same pattern
                self.rules = [r for r in self.rules if r.tool_pattern != rule.tool_pattern]
                self.rules.append(rule)

            # Also load category shortcuts
            categories = data.get("categories", {})
            for category, perm_value in categories.items():
                perm = Permission(perm_value)
                if category == "read":
                    self.set("shutong_file_read", perm)
                    self.set("shutong_grep", perm)
                    self.set("shutong_glob", perm)
                    self.set("shutong_file_list", perm)
                elif category == "edit":
                    self.set("shutong_file_write", perm)
                    self.set("shutong_file_edit", perm)
                elif category == "bash":
                    self.set("shutong_bash", perm)
                elif category == "network":
                    self.set("shutong_bash", perm)

            logger.info("Loaded %d permission rules from %s", len(self.rules), config_path)
        except Exception as exc:
            logger.warning("Failed to load permission config from %s: %s", config_path, exc)

    def save_config(self, config_path: Optional[str] = None) -> None:
        """Save current permission rules to a JSON config file."""
        path = Path(config_path or self._config_path or ".shutong/permissions.json")
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "rules": [r.to_dict() for r in self.rules],
            "categories": {
                "read": self.check("shutong_file_read").value,
                "edit": self.check("shutong_file_edit").value,
                "bash": self.check("shutong_bash").value,
            },
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def list_rules(self) -> List[Dict[str, str]]:
        """Return all rules as a list of dicts."""
        return [r.to_dict() for r in self.rules]

    def check_with_context(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Check permission and return a structured response.

        Returns:
            {"status": "allowed", "tool": ..., "params": ...} if ALLOW
            {"status": "needs_permission", "tool": ..., "params": ..., "risk_level": ...} if ASK
            {"status": "denied", "tool": ..., "message": ...} if DENY
        """
        perm = self.check(tool_name)

        if perm == Permission.ALLOW:
            return {"status": "allowed", "tool": tool_name, "params": params}

        if perm == Permission.DENY:
            return {
                "status": "denied",
                "tool": tool_name,
                "message": f"Permission denied for {tool_name}. Use /permissions to configure.",
                "params": params,
            }

        # ASK — determine risk level
        destructive_tools = {"shutong_bash", "shutong_file_write", "shutong_file_edit", "shutong_delete_document"}
        risk = "high" if tool_name in destructive_tools else "medium"

        return {
            "status": "needs_permission",
            "tool": tool_name,
            "params": params,
            "risk_level": risk,
        }