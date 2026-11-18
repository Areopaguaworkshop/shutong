"""Draft Agent — generate section-by-section prose from an outline and evidence.

Takes a WritingOutline + evidence, produces prose draft sections with citations.
Uses Ollama for LLM-based drafting with deterministic fallback.
"""

import json
import logging
import os
import subprocess
from typing import Any, Dict, List, Optional

from ..models import SCHEMA_VERSION

logger = logging.getLogger(__name__)


class DraftAgent:
    """Generate a section-by-section prose draft from an outline."""

    def __init__(self, schema_version: str = SCHEMA_VERSION, llm_model: str = "") -> None:
        self.schema_version = schema_version
        self.llm_model = llm_model or os.environ.get("SHUTONG_LLM_MODEL", "glm-5.3-flash:cloud")

    def generate(
        self,
        outline: Dict[str, Any],
        evidence: Dict[str, Any],
        style: str = "academic",
        glossary: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Generate a draft from the outline and evidence.

        Returns a WritingDraft dict with draft_id, outline_id, sections, and total_word_count.
        """
        import hashlib
        draft_id = f"draft-{hashlib.sha256(outline.get('outline_id', 'x').encode()).hexdigest()[:8]}"

        sections = []
        outline_sections = outline.get("sections", [])

        for sec_idx, section in enumerate(outline_sections):
            section_draft = self._draft_section(section, evidence, style, glossary, sec_idx)
            sections.append(section_draft)

        total_words = sum(s.get("word_count", 0) for s in sections)

        return {
            "schema_version": self.schema_version,
            "draft_id": draft_id,
            "outline_id": outline.get("outline_id", ""),
            "title": outline.get("title", ""),
            "sections": sections,
            "total_word_count": total_words,
            "style": style,
        }

    def _draft_section(
        self,
        section: Dict[str, Any],
        evidence: Dict[str, Any],
        style: str,
        glossary: Optional[Dict[str, str]],
        sec_idx: int,
    ) -> Dict[str, Any]:
        """Draft a single section, trying LLM first with fallback."""
        heading = section.get("heading", f"Section {sec_idx + 1}")
        subsections = section.get("subsections", [])

        # Gather claims for this section
        claims = []
        for sub in subsections:
            for claim in sub.get("key_claims", []):
                claims.append(claim.get("claim", ""))

        # Try LLM generation
        llm_prose = self._llm_draft_section(heading, claims, evidence, style, glossary)
        if llm_prose:
            word_count = len(llm_prose.split())
            citations = self._extract_citations(llm_prose)
            return {
                "section_id": f"s-{sec_idx + 1}",
                "heading": heading,
                "prose": llm_prose,
                "citations": citations,
                "word_count": word_count,
            }

        # Fallback: structured template
        prose = self._fallback_section(heading, subsections, evidence)
        word_count = len(prose.split())
        citations = self._extract_citations(prose)
        return {
            "section_id": f"s-{sec_idx + 1}",
            "heading": heading,
            "prose": prose,
            "citations": citations,
            "word_count": word_count,
        }

    def _llm_draft_section(
        self,
        heading: str,
        claims: List[str],
        evidence: Dict[str, Any],
        style: str,
        glossary: Optional[Dict[str, str]],
    ) -> Optional[str]:
        """Attempt LLM-based section drafting."""
        claims_text = "\n".join(f"- {c}" for c in claims[:10])
        evidence_nodes = evidence.get("ranked_nodes", [])[:5]
        evidence_text = "\n".join(
            f"- {n.get('text', '')[:200]}" for n in evidence_nodes
        )

        glossary_note = ""
        if glossary:
            terms = ", ".join(f"{en} → {zh}" for en, zh in list(glossary.items())[:10])
            glossary_note = f"\nMandatory glossary terms: {terms}"

        prompt = f"""Write an academic section titled "{heading}" in {style} style.

Key claims to address:
{claims_text}

Available evidence:
{evidence_text}
{glossary_note}

Requirements:
- Support each claim with evidence, citing sources using (Author Year) format
- Write 200-400 words
- Be precise and avoid hedging unless the evidence is genuinely uncertain
- Do NOT use filler phrases like "It is important to note" or "Furthermore"
- Use specific language rather than vague generalizations

Write the section prose:"""

        model_name = self.llm_model.replace("ollama/", "") if self.llm_model.startswith("ollama/") else self.llm_model

        from ...llm.provider import ollama_model_available
        if not ollama_model_available(model_name):
            logger.warning("Model %s not available locally; using deterministic fallback", model_name)
            return None

        try:
            result = subprocess.run(
                ["ollama", "run", model_name, prompt],
                capture_output=True, text=True, timeout=180,
                env={**os.environ, "OLLAMA_HOST": os.environ.get("OLLAMA_HOST", "http://localhost:11434")},
            )
            if result.returncode != 0:
                return None
            return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    @staticmethod
    def _fallback_section(
        heading: str,
        subsections: List[Dict[str, Any]],
        evidence: Dict[str, Any],
    ) -> str:
        """Generate a template-based section as fallback."""
        lines = [f"## {heading}", ""]
        for sub in subsections:
            sub_heading = sub.get("heading", "")
            if sub_heading:
                lines.append(f"### {sub_heading}")
                lines.append("")
            for claim in sub.get("key_claims", []):
                claim_text = claim.get("claim", "")
                source_hints = claim.get("source_hints", [])
                if source_hints:
                    cites = ", ".join(source_hints[:2])
                    lines.append(f"{claim_text} ({cites}).")
                else:
                    lines.append(f"{claim_text}.")
                lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _extract_citations(text: str) -> List[str]:
        """Extract citation keys from drafted text."""
        import re
        # Match (Author Year) patterns
        paren_cites = re.findall(r'\(([^)]*?\d{4}[^)]*?)\)', text)
        # Match [citation N] patterns
        bracket_cites = re.findall(r'\[citation[\s\d:]*\]', text)
        return list(set(paren_cites + bracket_cites))
