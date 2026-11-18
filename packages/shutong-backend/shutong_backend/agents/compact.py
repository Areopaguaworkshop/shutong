"""Context Compaction — summarize message history when approaching context limits.

Preserves citations and evidence references. Falls back to rule-based
extraction (first/last sentences) if LLM summarization fails.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Token estimation ───────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English text."""
    return max(1, len(text) // 4)


# ── Context Compactor ───────────────────────────────────────────────────


class ContextCompactor:
    """Summarize older messages when approaching context window limits.

    Strategy:
    1. Keep system messages and last N messages intact
    2. Summarize older messages into a single system message
    3. Preserve citation references and quality gate badges
    4. Track compaction count for transparency
    """

    def __init__(
        self,
        llm_model: str = "ollama/deepseek-v4-pro:cloud",
        max_tokens: int = 4000,
        keep_recent: int = 4,
    ) -> None:
        self.llm_model = llm_model
        self.max_tokens = max_tokens
        self.keep_recent = keep_recent

    def compact(self, messages: List[Dict[str, Any]], threshold_pct: float = 0.8) -> Dict[str, Any]:
        """Check if messages exceed threshold and compact if needed.

        Returns dict with:
            compacted: bool — whether compaction occurred
            messages: List[Dict] — the (possibly compacted) messages
            compaction_info: Dict with original_count, compacted_count, tokens_saved
        """
        total_tokens = sum(estimate_tokens(m.get("content", "")) for m in messages)
        threshold = int(self.max_tokens * threshold_pct)

        if total_tokens < threshold:
            return {
                "compacted": False,
                "messages": messages,
                "compaction_info": {
                    "original_count": len(messages),
                    "compacted_count": len(messages),
                    "tokens_saved": 0,
                },
            }

        return self._do_compact(messages)

    def _do_compact(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Perform the compaction."""
        if len(messages) <= self.keep_recent + 1:
            return {
                "compacted": False,
                "messages": messages,
                "compaction_info": {
                    "original_count": len(messages),
                    "compacted_count": len(messages),
                    "tokens_saved": 0,
                },
            }

        # Separate: system messages, older messages, recent messages
        system_msgs = [m for m in messages if m.get("role") == "system"]
        recent_msgs = messages[-self.keep_recent:]
        older_msgs = [m for m in messages if m not in system_msgs and m not in recent_msgs]

        if not older_msgs:
            return {
                "compacted": False,
                "messages": messages,
                "compaction_info": {
                    "original_count": len(messages),
                    "compacted_count": len(messages),
                    "tokens_saved": 0,
                },
            }

        # Extract citations from older messages
        citations = []
        for m in older_msgs:
            for c in m.get("citations", []):
                if c and c not in citations:
                    citations.append(c)

        # Try LLM-based summarization, fall back to rule-based
        summary = self._summarize_with_llm(older_msgs)
        if not summary:
            summary = self._summarize_rule_based(older_msgs)

        # Build compacted message list
        compacted_messages = list(system_msgs)
        compacted_messages.append({
            "role": "system",
            "content": f"[Context compacted: {len(older_msgs)} messages summarized]\n{summary}"
            + (f"\nCitations preserved: {', '.join(citations)}" if citations else ""),
            "citations": citations,
        })
        compacted_messages.extend(recent_msgs)

        original_tokens = sum(estimate_tokens(m.get("content", "")) for m in messages)
        compacted_tokens = sum(estimate_tokens(m.get("content", "")) for m in compacted_messages)
        tokens_saved = max(0, original_tokens - compacted_tokens)

        return {
            "compacted": True,
            "messages": compacted_messages,
            "compaction_info": {
                "original_count": len(messages),
                "compacted_count": len(compacted_messages),
                "tokens_saved": tokens_saved,
            },
        }

    def _summarize_with_llm(self, messages: List[Dict[str, Any]]) -> Optional[str]:
        """Try to summarize messages using the configured LLM."""
        try:
            from shutong_backend.llm import get_llm

            provider = get_llm(self.llm_model)
            model = getattr(provider, "_default_model", "")

            conversation_text = "\n".join(
                f"{m.get('role', 'unknown')}: {m.get('content', '')[:500]}"
                for m in messages
            )
            prompt = (
                f"Summarize the following conversation in 3-5 key points. "
                f"Preserve any citation references (e.g., '(Author, Year)'). "
                f"Keep the summary under 200 words.\n\n{conversation_text}"
            )
            result = provider.invoke(prompt, model=model)
            return result.strip() if result else None
        except Exception as exc:
            logger.debug("LLM compaction summary failed, using rule-based: %s", exc)
            return None

    def _summarize_rule_based(self, messages: List[Dict[str, Any]]) -> str:
        """Rule-based summarization fallback: take first and last sentences."""
        points = []
        for m in messages:
            content = m.get("content", "")
            role = m.get("role", "unknown")
            # Take first sentence
            first_sentence = re.split(r'[.!?]', content, maxsplit=1)[0].strip()
            if first_sentence:
                points.append(f"- [{role}] {first_sentence[:100]}")

        if not points:
            return f"Summary: {len(messages)} messages were compacted."

        # Keep max 10 points
        if len(points) > 10:
            half = 5
            points = points[:half] + points[-half:]

        return "Key points from compacted context:\n" + "\n".join(points)