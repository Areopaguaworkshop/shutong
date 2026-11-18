"""Material Passport — cross-session state carryover for research context.

Inspired by ARS's Material Passport concept. Stores research goals, open
questions, sources consulted, outlines, drafts, insights, contradictions,
style preferences, and glossary additions across sessions.
"""

import hashlib
import json
import os
import re
import time
from typing import Any, Dict, List, Optional

from .agents.models import SCHEMA_VERSION

# Passport IDs are generated as ``pp-<8 hex>``; anything else is rejected before
# it is joined into a filesystem path.
_PASSPORT_ID_PATTERN = r"pp-[0-9a-f]{8}"
_PASSPORT_ID_RE = re.compile(_PASSPORT_ID_PATTERN)


class InvalidPassportId(ValueError):
    """Raised when a caller-supplied passport ID is not a safe passport ID."""


def _validate_passport_id(passport_id: Any) -> str:
    if not isinstance(passport_id, str) or not _PASSPORT_ID_RE.fullmatch(passport_id):
        raise InvalidPassportId(
            f"Invalid passport id {passport_id!r}: expected '{_PASSPORT_ID_PATTERN}'."
        )
    return passport_id


class MaterialPassport:
    """Cross-session research state that persists between conversations."""

    def __init__(self, passport_dir: str = "", schema_version: str = SCHEMA_VERSION) -> None:
        self.passport_dir = passport_dir or os.path.join("corpus", ".shutong", "passport")
        self.schema_version = schema_version

    def create(self, project_name: str = "Untitled Project", research_goals: Optional[List[str]] = None) -> Dict[str, Any]:
        """Create a new passport."""
        passport_id = f"pp-{hashlib.sha256(project_name.encode()).hexdigest()[:8]}"
        passport = {
            "schema_version": self.schema_version,
            "passport_id": passport_id,
            "project_name": project_name,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "research_goals": research_goals or [],
            "open_questions": [],
            "sources_consulted": [],
            "outlines": [],
            "drafts": [],
            "key_insights": [],
            "contradictions_found": [],
            "style_preferences": {},
            "glossary_additions": [],
        }
        self._save(passport)
        return passport

    def load(self, passport_id: str) -> Optional[Dict[str, Any]]:
        """Load a passport by ID."""
        path = self._passport_path(passport_id)
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return json.load(f)

    def update(self, passport_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Merge updates into a passport (not replace)."""
        passport = self.load(passport_id)
        if not passport:
            return None
        for key, value in updates.items():
            if key in ("passport_id", "created_at", "schema_version"):
                continue  # Immutable fields
            if isinstance(value, list) and isinstance(passport.get(key), list):
                # Merge lists, avoiding duplicates
                existing = set(str(x) for x in passport[key])
                for item in value:
                    if str(item) not in existing:
                        passport[key].append(item)
                        existing.add(str(item))
            elif isinstance(value, dict) and isinstance(passport.get(key), dict):
                passport[key].update(value)
            else:
                passport[key] = value
        passport["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._save(passport)
        return passport

    def summary(self, passport_id: str, max_tokens: int = 500) -> str:
        """Generate a concise summary for context injection."""
        passport = self.load(passport_id)
        if not passport:
            return ""
        lines = [
            f"Project: {passport.get('project_name', 'Untitled')}",
            f"Goals: {', '.join(passport.get('research_goals', [])[:5]) or '(none set)'}",
            f"Sources consulted: {len(passport.get('sources_consulted', []))}",
            f"Open questions: {len(passport.get('open_questions', []))}",
            f"Key insights: {len(passport.get('key_insights', []))}",
        ]
        # Add top insights
        for insight in passport.get("key_insights", [])[:3]:
            lines.append(f"  - {insight.get('insight', '')[:80]}")
        # Add open questions
        for q in passport.get("open_questions", [])[:3]:
            lines.append(f"  ? {q.get('question', '')[:80]} [{q.get('status', 'open')}]")
        text = "\n".join(lines)
        if len(text) > max_tokens * 4:  # rough char estimate
            text = text[:max_tokens * 4]
        return text

    def list_passports(self) -> List[Dict[str, Any]]:
        """List all passports (summary only)."""
        if not os.path.exists(self.passport_dir):
            return []
        passports = []
        for fname in os.listdir(self.passport_dir):
            if fname.endswith(".json"):
                path = os.path.join(self.passport_dir, fname)
                with open(path) as f:
                    p = json.load(f)
                    passports.append({
                        "passport_id": p.get("passport_id", ""),
                        "project_name": p.get("project_name", ""),
                        "updated_at": p.get("updated_at", ""),
                        "sources_count": len(p.get("sources_consulted", [])),
                        "insights_count": len(p.get("key_insights", [])),
                    })
        return sorted(passports, key=lambda x: x.get("updated_at", ""), reverse=True)

    def _save(self, passport: Dict[str, Any]) -> None:
        os.makedirs(self.passport_dir, exist_ok=True)
        path = self._passport_path(passport.get("passport_id"))
        with open(path, "w") as f:
            json.dump(passport, f, indent=2, default=str)

    def _passport_path(self, passport_id: Any) -> str:
        """Validate a passport ID and resolve its path inside ``passport_dir``."""
        _validate_passport_id(passport_id)
        base = os.path.realpath(self.passport_dir)
        path = os.path.realpath(os.path.join(base, f"{passport_id}.json"))
        if os.path.dirname(path) != base:
            raise InvalidPassportId(f"Passport id escapes the passport directory: {passport_id!r}.")
        return path
