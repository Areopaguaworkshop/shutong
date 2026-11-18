"""Session Diary — auto-generated structured session summaries.

Stores per-session summaries at .shutong/diary/<date>.json with
topics, sources, insights, questions, and depth trends.
"""

import json
import os
import time
from typing import Any, Dict, List, Optional

from .agents.models import SCHEMA_VERSION


class DiaryEntry:
    """A single diary entry for a research session."""

    def __init__(
        self,
        entry_id: str = "",
        session_id: str = "",
        topics_discussed: Optional[List[str]] = None,
        sources_consulted: Optional[List[str]] = None,
        key_insights: Optional[List[str]] = None,
        open_questions: Optional[List[str]] = None,
        depth_trend: str = "stable",
        passport_updates: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.entry_id = entry_id or f"diary-{int(time.time())}"
        self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.session_id = session_id
        self.topics_discussed = topics_discussed or []
        self.sources_consulted = sources_consulted or []
        self.key_insights = key_insights or []
        self.open_questions = open_questions or []
        self.depth_trend = depth_trend
        self.passport_updates = passport_updates or {}
        self.schema_version = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "entry_id": self.entry_id,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "topics_discussed": self.topics_discussed,
            "sources_consulted": self.sources_consulted,
            "key_insights": self.key_insights,
            "open_questions": self.open_questions,
            "depth_trend": self.depth_trend,
            "passport_updates": self.passport_updates,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiaryEntry":
        entry = cls(
            entry_id=data.get("entry_id", ""),
            session_id=data.get("session_id", ""),
            topics_discussed=data.get("topics_discussed", []),
            sources_consulted=data.get("sources_consulted", []),
            key_insights=data.get("key_insights", []),
            open_questions=data.get("open_questions", []),
            depth_trend=data.get("depth_trend", "stable"),
            passport_updates=data.get("passport_updates", {}),
        )
        entry.timestamp = data.get("timestamp", entry.timestamp)
        return entry


class SessionDiary:
    """Manage session diary entries, persisted to .shutong/diary/."""

    def __init__(self, diary_dir: str = "") -> None:
        self.diary_dir = diary_dir or os.path.join("corpus", ".shutong", "diary")

    def save(self, entry: DiaryEntry) -> str:
        """Save a diary entry. Returns the entry ID."""
        os.makedirs(self.diary_dir, exist_ok=True)
        date_str = time.strftime("%Y-%m-%d")
        path = os.path.join(self.diary_dir, f"{date_str}.json")

        entries = []
        if os.path.exists(path):
            with open(path) as f:
                entries = json.load(f)

        entries.append(entry.to_dict())
        with open(path, "w") as f:
            json.dump(entries, f, indent=2, default=str)

        return entry.entry_id

    def load_date(self, date_str: str) -> List[DiaryEntry]:
        """Load all entries for a given date."""
        path = os.path.join(self.diary_dir, f"{date_str}.json")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            entries = json.load(f)
        return [DiaryEntry.from_dict(e) for e in entries]

    def list_dates(self) -> List[str]:
        """List all dates that have diary entries."""
        if not os.path.exists(self.diary_dir):
            return []
        dates = [f.replace(".json", "") for f in os.listdir(self.diary_dir) if f.endswith(".json")]
        return sorted(dates, reverse=True)

    def recent(self, count: int = 5) -> List[DiaryEntry]:
        """Get the most recent diary entries across all dates."""
        all_entries = []
        for date_str in self.list_dates()[:count]:
            all_entries.extend(self.load_date(date_str))
        return all_entries[:count]