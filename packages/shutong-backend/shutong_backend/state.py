"""ResearchState — unified facade over the scattered research-state stores.

Consolidates the Material Passport, knowledge graph, session diary, and
memory store behind one read/write surface with a single wake-up context
for session start. MemPalace (ChromaDB vector store) is intentionally left
out — it is a separate retrieval concern, not a research-state ledger.

This is a facade, not a rewrite: the existing stores remain the source of
truth; ResearchState only composes them and adds the two things that were
missing — a single wake-up context and a single record_session write path.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from .agents.memory import MemoryStore
from .diary import DiaryEntry, SessionDiary
from .graph import KnowledgeGraph
from .passport import MaterialPassport


class ResearchState:
    """One entry point for all cross-session research state."""

    def __init__(self, storage_dir: str = ".shutong") -> None:
        self.storage_dir = storage_dir
        self.passport = MaterialPassport(passport_dir=os.path.join(storage_dir, "passport"))
        self.graph = KnowledgeGraph(graph_dir=os.path.join(storage_dir, "graph"))
        self.diary = SessionDiary(diary_dir=os.path.join(storage_dir, "diary"))
        self.memory = MemoryStore(memory_dir=os.path.join(storage_dir, "memory"))

    # ── Wake-up context ──────────────────────────────────────────────

    def wake_up(self, passport_id: Optional[str] = None, max_tokens: int = 500) -> str:
        """Compact context for injection at session start.

        Prefers the named passport; otherwise falls back to the most recently
        updated passport. Appends recent diary topics and graph stats.
        """
        parts: List[str] = []

        if passport_id:
            summary = self.passport.summary(passport_id, max_tokens=max_tokens)
            if summary:
                parts.append(summary)
        else:
            passports = self.passport.list_passports()
            if passports:
                summary = self.passport.summary(passports[0]["passport_id"], max_tokens=max_tokens)
                if summary:
                    parts.append(summary)

        recent = self.diary.recent(count=3)
        if recent:
            lines = ["## Recent sessions"]
            for entry in recent:
                topics = ", ".join(entry.topics_discussed[:3]) or "(no topics)"
                lines.append(f"- {entry.timestamp}: {topics}")
            parts.append("\n".join(lines))

        stats = self.graph.stats()
        if stats.get("nodes"):
            parts.append(
                f"## Knowledge graph: {stats['nodes']} nodes, {stats['edges']} edges, "
                f"{stats.get('contradictions', 0)} contradictions"
            )

        return "\n\n".join(parts)

    # ── Unified snapshot ─────────────────────────────────────────────

    def snapshot(self) -> Dict[str, Any]:
        """One dict describing all research state, for status/visibility."""
        return {
            "passports": self.passport.list_passports(),
            "graph": self.graph.stats(),
            "diary_dates": self.diary.list_dates(),
            "memory_threads": self._memory_threads(),
        }

    def _memory_threads(self) -> List[Dict[str, Any]]:
        threads: List[Dict[str, Any]] = []
        for thread_id in self.memory._list_threads():  # noqa: SLF001
            entries = self.memory.load_thread(thread_id)
            threads.append(
                {
                    "thread_id": thread_id,
                    "entry_count": len(entries),
                    "latest_timestamp": entries[-1].timestamp if entries else None,
                }
            )
        return threads

    # ── One write path ───────────────────────────────────────────────

    def record_session(
        self,
        *,
        session_id: str,
        topics: List[str],
        sources: List[str],
        insights: List[str],
        open_questions: List[str],
        passport_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record a session across diary + passport in one call.

        The diary entry is always written. If a passport_id is given, the
        same sources/insights/questions are merged into that passport so the
        two ledgers never drift apart.
        """
        entry = DiaryEntry(
            session_id=session_id,
            topics_discussed=topics,
            sources_consulted=sources,
            key_insights=insights,
            open_questions=open_questions,
        )
        entry_id = self.diary.save(entry)
        result: Dict[str, Any] = {"diary_entry_id": entry_id}

        if passport_id:
            updates = {
                "sources_consulted": sources,
                "key_insights": [{"insight": i} for i in insights],
                "open_questions": [{"question": q, "status": "open"} for q in open_questions],
            }
            self.passport.update(passport_id, updates)
            result["passport_updated"] = passport_id

        return result
