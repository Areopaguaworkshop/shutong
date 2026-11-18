"""Writing Quality Agent — measure citation coverage, section balance, and readability.

All checks are deterministic (no LLM required).
"""

import logging
import re
import statistics
from typing import Any, Dict, List

from ..models import SCHEMA_VERSION

logger = logging.getLogger(__name__)


class WritingQualityAgent:
    """Run deterministic quality checks on a writing draft."""

    def __init__(self, schema_version: str = SCHEMA_VERSION) -> None:
        self.schema_version = schema_version

    def check(self, draft: Dict[str, Any]) -> Dict[str, Any]:
        """Run quality checks on a draft and return a WritingQualityReport."""
        sections = draft.get("sections", [])
        total_words = draft.get("total_word_count", 0)

        # Citation coverage
        citation_coverage = self._check_citation_coverage(sections)

        # Section balance
        section_balance = self._check_section_balance(sections)

        # Readability
        readability = self._check_readability(sections)

        # Passive voice ratio (aggregate across sections)
        passive_ratio = self._check_passive_ratio(sections)

        # Anti-AI-slop score (composite)
        anti_slop = self._compute_anti_slop(citation_coverage, section_balance, readability, passive_ratio)

        return {
            "schema_version": self.schema_version,
            "draft_id": draft.get("draft_id", ""),
            "total_word_count": total_words,
            "citation_coverage": round(citation_coverage, 3),
            "section_balance": round(section_balance, 3),
            "avg_sentence_length": round(readability.get("avg_length", 0), 1),
            "passive_voice_ratio": round(passive_ratio, 3),
            "anti_ai_slop_score": round(anti_slop, 3),
            "readability": readability,
        }

    def _check_citation_coverage(self, sections: List[Dict[str, Any]]) -> float:
        """Fraction of sections that contain at least one citation."""
        if not sections:
            return 1.0
        cited = sum(1 for s in sections if s.get("citations") and len(s.get("citations", [])) > 0)
        return cited / len(sections)

    def _check_section_balance(self, sections: List[Dict[str, Any]]) -> float:
        """How evenly distributed are word counts across sections (0=imbalanced, 1=balanced)."""
        if len(sections) < 2:
            return 1.0
        counts = [s.get("word_count", 0) for s in sections]
        if max(counts) == 0:
            return 0.0
        # Coefficient of variation inverted — low CV = high balance
        mean = statistics.mean(counts)
        if mean == 0:
            return 0.0
        stdev = statistics.stdev(counts) if len(counts) > 1 else 0
        cv = stdev / mean
        return max(0.0, 1.0 - cv)

    def _check_readability(self, sections: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Average sentence length and variance."""
        all_sentences = []
        for s in sections:
            prose = s.get("prose", "")
            sentences = re.split(r'(?<=[.!?])\s+', prose)
            all_sentences.extend([sent.strip() for sent in sentences if len(sent.strip()) > 5])

        if not all_sentences:
            return {"avg_length": 0, "stdev": 0, "count": 0}

        lengths = [len(sent.split()) for sent in all_sentences]
        return {
            "avg_length": round(statistics.mean(lengths), 1),
            "stdev": round(statistics.stdev(lengths), 1) if len(lengths) > 1 else 0,
            "count": len(lengths),
        }

    def _check_passive_ratio(self, sections: List[Dict[str, Any]]) -> float:
        """Aggregate passive voice ratio across all sections."""
        passive_patterns = [
            r'\bwas\s+\w+ed\b', r'\bwere\s+\w+ed\b', r'\bis\s+\w+ed\b',
            r'\bare\s+\w+ed\b', r'\bbeen\s+\w+ed\b', r'\bbeing\s+\w+ed\b',
        ]
        total_sentences = 0
        passive_sentences = 0
        for s in sections:
            prose = s.get("prose", "")
            sentences = re.split(r'(?<=[.!?])\s+', prose)
            for sent in sentences:
                if len(sent.strip()) < 5:
                    continue
                total_sentences += 1
                if any(re.search(p, sent, re.IGNORECASE) for p in passive_patterns):
                    passive_sentences += 1
        return passive_sentences / max(total_sentences, 1)

    def _compute_anti_slop(self, coverage: float, balance: float, readability: Dict, passive: float) -> float:
        """Composite anti-AI-slop score. 1.0 = human-like, 0.0 = AI-slop."""
        # Weighted composite: citations matter most, then balance, then readability variance
        avg_len = readability.get("avg_length", 0)
        stdev = readability.get("stdev", 0)
        cv = stdev / max(avg_len, 1)

        # Length variance score: high CV = varied = good
        variance_score = min(cv / 0.4, 1.0)  # CV > 0.4 is good

        # Passive penalty
        passive_score = max(0, 1.0 - passive * 3)  # >33% passive = 0

        # Weighted sum
        return (
            coverage * 0.35 +
            balance * 0.20 +
            variance_score * 0.25 +
            passive_score * 0.20
        )