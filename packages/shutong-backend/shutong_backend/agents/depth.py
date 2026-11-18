"""Depth Measurement — heuristic per-message engagement depth scoring.

Measures 5 dimensions per user message without requiring an LLM:
specificity, evidence_density, critical_thinking, synthesis, originality.
Produces a rolling composite score per session.
"""

import re
from typing import Any, Dict, List

from .models import SCHEMA_VERSION


class DepthMeasurement:
    """Measure collaborative depth of user messages."""

    def __init__(self, schema_version: str = SCHEMA_VERSION) -> None:
        self.schema_version = schema_version

    def measure(self, user_message: str, evidence_ids: List[str] = None, retrieved_ids: List[str] = None) -> Dict[str, Any]:
        """Compute depth dimensions for a single user message."""
        evidence_ids = evidence_ids or []
        retrieved_ids = retrieved_ids or []

        specificity = self._specificity(user_message)
        evidence_density = self._evidence_density(user_message, evidence_ids)
        critical_thinking = self._critical_thinking(user_message)
        synthesis = self._synthesis(user_message)
        originality = self._originality(user_message, retrieved_ids)

        # Composite: weighted average
        composite = (
            specificity * 0.25 +
            evidence_density * 0.20 +
            critical_thinking * 0.25 +
            synthesis * 0.15 +
            originality * 0.15
        )

        return {
            "schema_version": self.schema_version,
            "specificity": round(specificity, 3),
            "evidence_density": round(evidence_density, 3),
            "critical_thinking": round(critical_thinking, 3),
            "synthesis": round(synthesis, 3),
            "originality": round(originality, 3),
            "composite": round(composite, 3),
        }

    @staticmethod
    def _specificity(text: str) -> float:
        """Ratio of specific claims to hedging. Higher = more specific."""
        words = text.split()
        if not words:
            return 0.0
        # Specificity indicators: numbers, proper nouns, quoted terms
        numbers = len(re.findall(r'\b\d+\.?\d*\b', text))
        quoted = len(re.findall(r'"[^"]+"', text))
        proper_nouns = len(re.findall(r'\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)+\b', text))
        specific = numbers + quoted + proper_nouns

        # Hedging indicators
        hedges = len(re.findall(r'\b(may|might|could|possibly|perhaps|arguably|seems|appears)\b', text, re.IGNORECASE))

        if specific + hedges == 0:
            return 0.5
        return min(1.0, specific / (specific + hedges))

    @staticmethod
    def _evidence_density(user_message: str, evidence_ids: List[str]) -> float:
        """Number of cited nodes per 100 words."""
        words = len(user_message.split())
        if words == 0:
            return 0.0
        return min(1.0, len(evidence_ids) / max(words / 100, 1))

    @staticmethod
    def _critical_thinking(text: str) -> float:
        """Presence of counter-questions, challenges, analytical patterns."""
        lower = text.lower()
        patterns = [
            r'\bbut\b.*\?', r'\bhowever\b', r'\bwhat about\b',
            r'\bcounter\b', r'\bchallenge\b', r'\bcontradict\b',
            r'\bwhy\b.*\?', r'\bhow\b.*\?', r'\bevidence\b.*\?',
            r'\bassum\b', r'\bbias\b', r'\blimitation\b',
        ]
        matches = sum(1 for p in patterns if re.search(p, lower))
        return min(1.0, matches / 3.0)

    @staticmethod
    def _synthesis(text: str) -> float:
        """Whether user connects claims across sources."""
        connectors = [
            r'\bsimilarly\b', r'\bin contrast\b', r'\bwhile\b.*\balso\b',
            r'\bboth\b.*\band\b', r'\bcompared to\b', r'\bon the other hand\b',
            r'\bbuilding on\b', r'\bextending\b', r'\balong with\b',
        ]
        lower = text.lower()
        matches = sum(1 for p in connectors if re.search(p, lower))
        return min(1.0, matches / 2.0)

    @staticmethod
    def _originality(user_message: str, retrieved_ids: List[str]) -> float:
        """Whether user introduces ideas not in retrieved evidence.

        Heuristic: short messages asking about retrieved content score low;
        long messages with unique vocabulary score high.
        """
        words = user_message.split()
        if not words:
            return 0.0
        unique_vocab = len(set(w.lower() for w in words if len(w) > 4))
        vocab_ratio = unique_vocab / max(len(words), 1)
        # Higher vocabulary diversity suggests originality
        return min(1.0, vocab_ratio * 2)