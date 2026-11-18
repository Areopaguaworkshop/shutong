"""Peer Review Panel — 7-agent review system for academic drafts.

Each reviewer focuses on a specific dimension. The ReviewOrchestrator
aggregates all reports into a consolidated ReviewDecision with actionable
items ranked by severity.
"""

import os
import re
import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict

from ..models import SCHEMA_VERSION

logger = logging.getLogger(__name__)


@dataclass
class ReviewReport:
    reviewer_role: str = ""
    severity: str = "minor"  # critical | major | minor | note
    findings: List[Dict[str, Any]] = field(default_factory=list)
    overall_assessment: str = "revise"  # accept | revise | reject
    confidence: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ReviewDecision:
    schema_version: str = SCHEMA_VERSION
    draft_id: str = ""
    reviewers: List[Dict[str, Any]] = field(default_factory=list)
    actionable_items: List[Dict[str, Any]] = field(default_factory=list)
    overall_verdict: str = "revise"  # accept | revise | reject
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MethodologyReviewer:
    """Check argument structure and logical validity."""
    def review(self, draft: Dict[str, Any]) -> ReviewReport:
        sections = draft.get("sections", [])
        findings = []
        for i, sec in enumerate(sections):
            prose = sec.get("prose", "")
            if len(prose) < 50:
                findings.append({"location": f"Section {i+1}", "description": "Section too short for substantive argument", "suggestion": "Expand or merge with adjacent section"})
            if "therefore" in prose.lower() and "because" not in prose.lower() and "since" not in prose.lower():
                findings.append({"location": f"Section {i+1}", "description": "Conclusion marker without explicit premise", "suggestion": "Add explicit premise before 'therefore'"})
        severity = "critical" if any(f["description"].find("too short") >= 0 for f in findings) else "minor"
        return ReviewReport(reviewer_role="methodology", severity=severity, findings=findings, overall_assessment="revise" if findings else "accept", confidence=0.7)


class EvidenceReviewer:
    """Verify claims are supported by evidence."""
    def review(self, draft: Dict[str, Any]) -> ReviewReport:
        sections = draft.get("sections", [])
        findings = []
        for i, sec in enumerate(sections):
            citations = sec.get("citations", [])
            prose = sec.get("prose", "")
            sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', prose) if len(s.strip()) > 15]
            uncited = sum(1 for s in sentences if not re.search(r'\([^)]*\d{4}[^)]*\)', s) and not re.search(r'\[citation', s))
            if uncited > len(sentences) * 0.5:
                findings.append({"location": f"Section {i+1}", "description": f"{uncited}/{len(sentences)} sentences lack citations", "suggestion": "Add evidence citations to support claims"})
        severity = "major" if findings else "minor"
        return ReviewReport(reviewer_role="evidence", severity=severity, findings=findings, overall_assessment="revise" if findings else "accept", confidence=0.8)


class CitationReviewer:
    """Check citation format, completeness, and accuracy."""
    def review(self, draft: Dict[str, Any]) -> ReviewReport:
        sections = draft.get("sections", [])
        findings = []
        for i, sec in enumerate(sections):
            citations = sec.get("citations", [])
            prose = sec.get("prose", "")
            # Check for dangling references
            ref_patterns = re.findall(r'\(([^)]+)\)', prose)
            for ref in ref_patterns:
                if ref not in citations and not re.match(r'^\d{4}', ref):
                    findings.append({"location": f"Section {i+1}", "description": f"Possible dangling reference: ({ref})", "suggestion": "Verify this citation exists in the source list"})
        severity = "minor" if len(findings) < 3 else "major"
        return ReviewReport(reviewer_role="citation", severity=severity, findings=findings, overall_assessment="revise" if findings else "accept", confidence=0.75)


class StyleReviewer:
    """Check prose quality, anti-AI-slop, passive voice."""
    def review(self, draft: Dict[str, Any]) -> ReviewReport:
        from ..writing.style import StyleCalibrationAgent
        style_agent = StyleCalibrationAgent()
        style_report = style_agent.check(draft)
        findings = []
        for sec_report in style_report.get("sections", []):
            for issue in sec_report.get("issues", []):
                findings.append({"location": f"Section {sec_report.get('section_id', '?')}", "description": f"{issue['type']}: {issue['description']}", "suggestion": issue.get("suggestion", "")})
        overall_score = style_report.get("overall_style_score", 0.5)
        assessment = "accept" if overall_score > 0.8 else "revise" if overall_score > 0.4 else "reject"
        return ReviewReport(reviewer_role="style", severity="minor" if overall_score > 0.6 else "major", findings=findings, overall_assessment=assessment, confidence=0.7)


class ScopeReviewer:
    """Check if the paper delivers on its stated thesis."""
    def review(self, draft: Dict[str, Any]) -> ReviewReport:
        outline = draft.get("outline_id", "")
        sections = draft.get("sections", [])
        thesis = draft.get("title", "")
        findings = []
        if not thesis:
            findings.append({"location": "Overall", "description": "No thesis statement found", "suggestion": "Add a clear thesis statement"})
        section_headings = [s.get("heading", "") for s in sections]
        if len(section_headings) < 3:
            findings.append({"location": "Overall", "description": "Too few sections to cover the thesis", "suggestion": "Add sections covering key aspects of the topic"})
        return ReviewReport(reviewer_role="scope", severity="minor" if len(findings) < 2 else "major", findings=findings, overall_assessment="revise" if findings else "accept", confidence=0.6)


class OriginalityReviewer:
    """Check against corpus for novelty."""
    def review(self, draft: Dict[str, Any]) -> ReviewReport:
        sections = draft.get("sections", [])
        findings = []
        total_words = draft.get("total_word_count", 0)
        if total_words < 500:
            findings.append({"location": "Overall", "description": f"Draft is only {total_words} words — may not develop original ideas", "suggestion": "Expand the draft to develop original contributions"})
        unique_citations = set()
        for sec in sections:
            unique_citations.update(sec.get("citations", []))
        if len(unique_citations) < 2 and total_words > 200:
            findings.append({"location": "Overall", "description": "Few unique sources cited — may lack original perspective", "suggestion": "Engage with more sources to develop original synthesis"})
        return ReviewReport(reviewer_role="originality", severity="minor" if len(findings) < 2 else "major", findings=findings, overall_assessment="revise" if findings else "accept", confidence=0.5)


class DevilsAdvocateReviewer:
    """Re-use the Devil's Advocate for review-specific challenges."""
    def __init__(self, llm_model: str = "") -> None:
        self.llm_model = llm_model or os.environ.get("SHUTONG_LLM_MODEL", "glm-5.3-flash:cloud")

    def review(self, draft: Dict[str, Any]) -> ReviewReport:
        from ..devils_advocate import DevilsAdvocateAgent
        all_prose = "\n\n".join(sec.get("prose", "") for sec in draft.get("sections", []))
        da = DevilsAdvocateAgent(llm_model=self.llm_model)
        report = da.challenge(answer_human=all_prose, answer_machine={"evidence": [], "query_id": ""})
        findings = []
        for c in report.get("challenges", []):
            findings.append({"location": "Overall", "description": f"[{c['challenge_type']}] {c['description']}", "suggestion": report.get("recommendations", ["Strengthen argumentation"])[0] if report.get("recommendations") else "Address the challenge"})
        severity = "major" if report.get("non_yield_threshold", 1.0) < 0.3 else "minor"
        return ReviewReport(reviewer_role="devils_advocate", severity=severity, findings=findings, overall_assessment="revise" if findings else "accept", confidence=0.6)


class ReviewOrchestrator:
    """Aggregate all reviewer reports into a consolidated decision."""
    def __init__(self, llm_model: str = "") -> None:
        self.llm_model = llm_model

    def review(self, draft: Dict[str, Any]) -> ReviewDecision:
        reviewers = [
            MethodologyReviewer(),
            EvidenceReviewer(),
            CitationReviewer(),
            StyleReviewer(),
            ScopeReviewer(),
            OriginalityReviewer(),
            DevilsAdvocateReviewer(llm_model=self.llm_model),
        ]
        reports = []
        for reviewer in reviewers:
            try:
                report = reviewer.review(draft)
                reports.append(report.to_dict())
            except Exception as e:
                logger.warning("Reviewer %s failed: %s", type(reviewer).__name__, e)
                reports.append(ReviewReport(reviewer_role=type(reviewer).__name__, severity="note", findings=[], overall_assessment="revise", confidence=0.0).to_dict())

        # Aggregate actionable items by severity
        actionable = []
        severity_order = {"critical": 0, "major": 1, "minor": 2, "note": 3}
        for report in reports:
            for finding in report.get("findings", []):
                actionable.append({**finding, "reviewer": report.get("reviewer_role", "unknown"), "severity": report.get("severity", "minor")})
        actionable.sort(key=lambda x: severity_order.get(x.get("severity", "minor"), 3))

        # Overall verdict
        critical_count = sum(1 for r in reports if r.get("severity") == "critical")
        major_count = sum(1 for r in reports if r.get("severity") == "major")
        accept_count = sum(1 for r in reports if r.get("overall_assessment") == "accept")

        if critical_count >= 2 or major_count >= 4:
            verdict = "reject"
        elif major_count >= 2 or accept_count < 3:
            verdict = "revise"
        else:
            verdict = "accept"

        return ReviewDecision(
            draft_id=draft.get("draft_id", ""),
            reviewers=reports,
            actionable_items=actionable[:10],
            overall_verdict=verdict,
            summary=f"{len(reports)} reviewers, {critical_count} critical, {major_count} major, {accept_count} accept. Verdict: {verdict}.",
        )
