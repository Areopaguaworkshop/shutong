"""Style Calibration Agent — detect and flag AI-generated writing patterns.

Checks draft text against style guidelines and detects common AI-slop
patterns: filler phrases, hedging, repetitive sentence openings,
passive voice overuse, and excessive semicolons/em-dashes.
"""

import logging
import re
from typing import Any, Dict, List

from ..models import SCHEMA_VERSION

logger = logging.getLogger(__name__)

# ── AI Slop Patterns ──────────────────────────────────────────────────

FILLER_PHRASES = [
    "it is important to note",
    "it is worth noting",
    "it should be noted",
    "it is worth mentioning",
    "in conclusion",
    "in summary",
    "to summarize",
    "furthermore",
    "moreover",
    "additionally",
    "it is essential to",
    "it is crucial to",
    "as mentioned earlier",
    "as previously stated",
    "in other words",
    "that is to say",
    "needless to say",
    "it goes without saying",
]

REPETITIVE_OPENERS = [
    "this",
    "the",
    "it",
    "there",
    "these",
    "those",
]

PASSIVE_SIGNALS = [
    r"\bwas\s+\w+ed\b",
    r"\bwere\s+\w+ed\b",
    r"\bis\s+\w+ed\b",
    r"\bare\s+\w+ed\b",
    r"\bbeen\s+\w+ed\b",
    r"\bbeing\s+\w+ed\b",
]


class StyleCalibrationAgent:
    """Detect AI-generated writing patterns and suggest style improvements."""

    def __init__(self, schema_version: str = SCHEMA_VERSION) -> None:
        self.schema_version = schema_version

    def check(self, draft: Dict[str, Any]) -> Dict[str, Any]:
        """Run style checks on each section of a draft.

        Returns a dict with per-section StyleReports and an overall score.
        """
        sections = draft.get("sections", [])
        section_reports = []
        total_score = 0.0
        total_issues = 0

        for section in sections:
            report = self._check_section(section)
            section_reports.append(report)
            total_score += report.get("style_score", 0.0)
            total_issues += len(report.get("issues", []))

        overall_score = total_score / max(len(sections), 1) if sections else 0.0

        return {
            "schema_version": self.schema_version,
            "draft_id": draft.get("draft_id", ""),
            "sections": section_reports,
            "overall_style_score": round(overall_score, 3),
            "total_issues": total_issues,
        }

    def _check_section(self, section: Dict[str, Any]) -> Dict[str, Any]:
        """Run all style checks on a single section."""
        prose = section.get("prose", "")
        section_id = section.get("section_id", "")
        issues: List[Dict[str, Any]] = []

        # 1. Filler phrase detection
        filler_issues = self._check_filler(prose)
        issues.extend(filler_issues)

        # 2. Repetitive sentence openers
        opener_issues = self._check_openers(prose)
        issues.extend(opener_issues)

        # 3. Passive voice ratio
        passive_issues = self._check_passive(prose)
        issues.extend(passive_issues)

        # 4. Semicolon/em-dash overuse
        punct_issues = self._check_punctuation(prose)
        issues.extend(punct_issues)

        # 5. Sentence length variance
        variance_issues = self._check_length_variance(prose)
        issues.extend(variance_issues)

        # Compute style score (0.0 = many issues, 1.0 = clean)
        sentences = self._split_sentences(prose)
        n = max(len(sentences), 1)
        score = max(0.0, 1.0 - (len(issues) / (n * 0.5 + 1)))

        return {
            "section_id": section_id,
            "heading": section.get("heading", ""),
            "style_score": round(score, 3),
            "issues": issues,
        }

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if len(s.strip()) > 5]

    def _check_filler(self, prose: str) -> List[Dict[str, Any]]:
        """Detect AI filler phrases."""
        issues = []
        lower = prose.lower()
        for phrase in FILLER_PHRASES:
            if phrase in lower:
                # Find the sentence containing it
                idx = lower.index(phrase)
                start = max(0, prose.rfind(".", 0, idx) + 1)
                end = min(len(prose), prose.find(".", idx) + 1) if prose.find(".", idx) != -1 else len(prose)
                issues.append({
                    "type": "filler_phrase",
                    "description": f"Remove filler phrase: \"{phrase}\"",
                    "suggestion": "Replace with specific, direct language.",
                    "severity": "minor",
                    "location": prose[start:end].strip()[:80],
                })
        return issues

    def _check_openers(self, prose: str) -> List[Dict[str, Any]]:
        """Detect repetitive sentence openers."""
        sentences = self._split_sentences(prose)
        if len(sentences) < 3:
            return []

        first_words = [s.split()[0].lower() for s in sentences if s.split()]
        from collections import Counter
        opener_counts = Counter(first_words)
        issues = []
        for word, count in opener_counts.items():
            ratio = count / len(sentences)
            if count >= 3 and ratio > 0.25:
                issues.append({
                    "type": "repetitive_opener",
                    "description": f"\"{word}\" starts {count}/{len(sentences)} sentences ({ratio:.0%})",
                    "suggestion": f"Vary sentence openings — use different structures to avoid \"{word}\" repetition.",
                    "severity": "minor",
                })
        return issues

    def _check_passive(self, prose: str) -> List[Dict[str, Any]]:
        """Check passive voice ratio."""
        sentences = self._split_sentences(prose)
        if not sentences:
            return []

        passive_count = 0
        for s in sentences:
            if any(re.search(p, s, re.IGNORECASE) for p in PASSIVE_SIGNALS):
                passive_count += 1

        ratio = passive_count / len(sentences)
        if ratio > 0.3:
            return [{
                "type": "passive_voice",
                "description": f"{passive_count}/{len(sentences)} sentences use passive voice ({ratio:.0%})",
                "suggestion": "Use active voice where possible — make the subject the doer.",
                "severity": "major" if ratio > 0.5 else "minor",
            }]
        return []

    def _check_punctuation(self, prose: str) -> List[Dict[str, Any]]:
        """Check for semicolon and em-dash overuse."""
        issues = []
        sentences = self._split_sentences(prose)
        n = max(len(sentences), 1)

        semicolons = prose.count(";")
        em_dashes = prose.count("—") + prose.count("--")
        total_punct = semicolons + em_dashes

        if total_punct / n > 0.5:
            issues.append({
                "type": "punctuation_overuse",
                "description": f"{semicolons} semicolons, {em_dashes} em-dashes across {n} sentences",
                "suggestion": "Reduce semicolons and em-dashes — use periods for clearer sentences.",
                "severity": "minor",
            })
        return issues

    def _check_length_variance(self, prose: str) -> List[Dict[str, Any]]:
        """Check for uniform sentence lengths (common AI pattern)."""
        sentences = self._split_sentences(prose)
        if len(sentences) < 4:
            return []

        lengths = [len(s.split()) for s in sentences]
        import statistics
        stdev = statistics.stdev(lengths) if len(lengths) > 1 else 0
        mean = statistics.mean(lengths)

        # Low coefficient of variation = uniform lengths = likely AI
        cv = stdev / mean if mean > 0 else 0
        if cv < 0.3 and mean > 10:
            return [{
                "type": "uniform_length",
                "description": f"Sentences average {mean:.0f} words with low variance (CV={cv:.2f})",
                "suggestion": "Vary sentence length — mix short punchy sentences with longer explanatory ones.",
                "severity": "minor",
            }]
        return []