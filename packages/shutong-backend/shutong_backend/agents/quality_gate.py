"""Content Quality Gate — deterministic quality checks on generated answers.

Runs after generation and before integrity verification.
All checks are rule-based (no LLM required).

Inspired by ARS's 7 AI failure-mode checklist, adapted for Shutong's
citation-grounded architecture. Checks for unsubstantiated claims,
excessive hedging, poor evidence utilization, sycophancy, and
self-contradiction.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from .models import QualityCheck, QualityReport, SCHEMA_VERSION

logger = logging.getLogger(__name__)

# ── Patterns ──────────────────────────────────────────────────────────

HEDGE_PHRASES = [
    "may", "might", "could", "possibly", "perhaps", "it seems",
    "it appears", "arguably", "it could be said", "one might consider",
    "in some sense", "to some extent", "it is possible that",
    "it is conceivable that", "potentially", "presumably",
]

FLATTERY_PATTERNS = [
    r"(?i)great question[!.]",
    r"(?i)excellent question[!.]",
    r"(?i)that'?s a (great|excellent|good|wonderful|fantastic) (point|question)",
    r"(?i)you'?re (right|correct) (to|that|in)",
    r"(?i)indeed,? (that is|this is|it is) (an? |a )?(important|key|crucial|good)",
    r"(?i)thank you for (asking|raising|bringing up)",
    r"(?i)that is (an? |a )?(important|excellent|interesting|perceptive) (point|observation|question)",
]

CITATION_PATTERNS = [
    r"\[citation[\s\d:]*\]",
    r"\([^)]*\d{4}[^)]*\)",  # (Author Year)
    r"\([^)]*et al\.?\s*\d{4}[^)]*\)",  # (Author et al. Year)
]


class ContentQualityGate:
    """Run deterministic quality checks on a generated answer."""

    def __init__(self, schema_version: str = SCHEMA_VERSION) -> None:
        self.schema_version = schema_version

    def check(
        self,
        answer_human: str,
        answer_machine: Dict[str, Any],
        retrieval_result: Optional[Dict[str, Any]] = None,
    ) -> QualityReport:
        """Run all quality checks and produce a report."""
        checks: List[QualityCheck] = []
        violations: List[str] = []
        suggestions: List[str] = []

        # Check 1: Unsubstantiated claims
        unsub = self._check_unsubstantiated_claims(answer_human)
        checks.append(unsub)
        if not unsub.passed:
            violations.extend(unsub.violations)
            suggestions.append(
                f"Add citations to {len(unsub.violations)} unsupported sentence(s)."
            )

        # Check 2: Hedge density
        hedge = self._check_hedge_density(answer_human)
        checks.append(hedge)

        # Check 3: Evidence utilization
        evidence = self._check_evidence_utilization(answer_machine, retrieval_result)
        checks.append(evidence)

        # Check 4: Anti-flattery
        flattery = self._check_flattery(answer_human)
        checks.append(flattery)
        if not flattery.passed:
            violations.extend(flattery.violations)
            suggestions.append("Remove sycophantic language.")

        # Check 5: Self-contradiction
        contradiction = self._check_self_contradiction(answer_human)
        checks.append(contradiction)
        if not contradiction.passed:
            violations.extend(contradiction.violations)
            suggestions.append("Resolve contradictory statements.")

        # Determine overall status
        critical_failures = [
            c for c in checks if not c.passed and c.check_type
            in ("unsubstantiated_claims", "self_contradiction")
        ]
        flagged = [c for c in checks if not c.passed and c not in critical_failures]

        if critical_failures:
            status = "rejected"
        elif flagged:
            status = "flagged"
        else:
            status = "approved"

        anti_flattery_score = flattery.score
        depth_score = 1.0 - hedge.score  # inverse: less hedging = more depth

        return QualityReport(
            schema_version=self.schema_version,
            status=status,
            checks=[c.to_dict() for c in checks],
            violations=violations,
            suggestions=suggestions,
            anti_flattery_score=anti_flattery_score,
            depth_score=depth_score,
        )

    # ── Individual checks ──────────────────────────────────────────────

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        """Split text into sentences (simple heuristic)."""
        sentences = re.split(r'(?<=[.!?。！？])\s+', text.strip())
        return [s for s in sentences if len(s) > 10]

    @staticmethod
    def _has_citation(sentence: str) -> bool:
        """Check if a sentence contains a citation marker."""
        for pattern in CITATION_PATTERNS:
            if re.search(pattern, sentence):
                return True
        return False

    def _check_unsubstantiated_claims(self, answer: str) -> QualityCheck:
        """Sentences without citation markers are unsubstantiated."""
        sentences = self._split_sentences(answer)
        if not sentences:
            return QualityCheck(
                check_type="unsubstantiated_claims",
                passed=True,
                score=1.0,
                detail="No sentences to check.",
            )

        unsupported = []
        for s in sentences:
            if not self._has_citation(s):
                unsupported.append(s[:80] + ("..." if len(s) > 80 else ""))

        ratio = 1.0 - (len(unsupported) / len(sentences))
        passed = ratio >= 0.6  # At least 60% of sentences should be cited

        return QualityCheck(
            check_type="unsubstantiated_claims",
            passed=passed,
            score=round(ratio, 3),
            detail=f"{len(unsupported)}/{len(sentences)} sentences lack citations.",
            violations=unsupported[:5],  # Cap at 5 to avoid bloat
        )

    def _check_hedge_density(self, answer: str) -> QualityCheck:
        """Ratio of hedging phrases to total sentences."""
        sentences = self._split_sentences(answer)
        if not sentences:
            return QualityCheck(
                check_type="hedge_density",
                passed=True,
                score=0.0,
                detail="No sentences to check.",
            )

        hedged_count = 0
        for s in sentences:
            lower = s.lower()
            if any(phrase in lower for phrase in HEDGE_PHRASES):
                hedged_count += 1

        ratio = hedged_count / len(sentences)
        passed = ratio < 0.3  # Less than 30% hedging is acceptable

        return QualityCheck(
            check_type="hedge_density",
            passed=passed,
            score=round(ratio, 3),
            detail=f"{hedged_count}/{len(sentences)} sentences contain hedging ({ratio:.0%}).",
        )

    def _check_evidence_utilization(
        self,
        answer_machine: Dict[str, Any],
        retrieval_result: Optional[Dict[str, Any]],
    ) -> QualityCheck:
        """Fraction of retrieved evidence nodes actually cited in the answer."""
        evidence = answer_machine.get("evidence", [])
        if not evidence or not retrieval_result:
            return QualityCheck(
                check_type="evidence_utilization",
                passed=True,
                score=1.0,
                detail="No evidence to check.",
            )

        cited_ids = {e.get("node_id", "") for e in evidence if e.get("node_id")}

        # Get available node IDs from retrieval result
        available_nodes = retrieval_result.get("ranked_nodes", [])
        available_ids = {n.get("node_id", "") for n in available_nodes if n.get("node_id")}

        if not available_ids:
            return QualityCheck(
                check_type="evidence_utilization",
                passed=True,
                score=1.0,
                detail="No retrieved nodes to compare.",
            )

        utilization = len(cited_ids & available_ids) / len(available_ids)
        passed = utilization >= 0.3  # At least 30% of retrieved evidence used

        return QualityCheck(
            check_type="evidence_utilization",
            passed=passed,
            score=round(utilization, 3),
            detail=f"{len(cited_ids & available_ids)}/{len(available_ids)} retrieved nodes cited ({utilization:.0%}).",
        )

    def _check_flattery(self, answer: str) -> QualityCheck:
        """Detect sycophantic patterns."""
        matches = []
        for pattern in FLATTERY_PATTERNS:
            found = re.findall(pattern, answer)
            matches.extend(found)

        # Score: 0.0 = no flattery, 1.0 = very sycophantic
        score = min(len(matches) / 3.0, 1.0)  # Normalize: 3+ matches = max
        passed = len(matches) == 0

        return QualityCheck(
            check_type="anti_flattery",
            passed=passed,
            score=round(score, 3),
            detail=f"{len(matches)} sycophantic pattern(s) detected.",
            violations=matches[:5],
        )

    def _check_self_contradiction(self, answer: str) -> QualityCheck:
        """Detect X is Y / X is not Y patterns in the same answer."""
        # Extract simple assertion patterns: "X is Y" and "X is not Y"
        positive = re.findall(r'(\b[\w\s]{3,30})\s+is\s+([\w\s]{3,30})', answer, re.IGNORECASE)
        negative = re.findall(r'(\b[\w\s]{3,30})\s+is not\s+([\w\s]{3,30})', answer, re.IGNORECASE)

        contradictions = []
        pos_dict = {subj.strip().lower(): obj.strip().lower() for subj, obj in positive}
        for subj, obj in negative:
            subj_lower = subj.strip().lower()
            obj_lower = obj.strip().lower()
            if subj_lower in pos_dict and pos_dict[subj_lower] == obj_lower:
                contradictions.append(f"'{subj} is {obj}' vs '{subj} is not {obj}'")

        passed = len(contradictions) == 0
        return QualityCheck(
            check_type="self_contradiction",
            passed=passed,
            score=round(len(contradictions) / 3.0, 3),  # 3+ = max
            detail=f"{len(contradictions)} contradiction(s) detected.",
            violations=contradictions[:5],
        )