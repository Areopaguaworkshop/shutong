"""Devil's Advocate Agent — adversarial checking of answers and claims.

Takes an answer + evidence, produces counter-arguments. Explicitly instructed
to find weaknesses, not to be agreeable. Computes a non-yield threshold
measuring how well the original answer addresses the challenges.

Uses Ollama for challenge generation with deterministic fallback.
"""

import json
import logging
import os
import re
import subprocess
from typing import Any, Dict, List, Optional

from .models import SCHEMA_VERSION

logger = logging.getLogger(__name__)

CHALLENGE_TYPES = [
    "unverified_assumption",
    "counter_evidence",
    "scope_overreach",
    "missing_perspective",
]


class DevilsAdvocateAgent:
    """Generate adversarial challenges against an answer."""

    def __init__(self, schema_version: str = SCHEMA_VERSION, llm_model: str = "") -> None:
        self.schema_version = schema_version
        self.llm_model = llm_model or os.environ.get("SHUTONG_LLM_MODEL", "glm-5.3-flash:cloud")

    def challenge(
        self,
        answer_human: str,
        answer_machine: Dict[str, Any],
        evidence_nodes: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Produce counter-arguments against the answer.

        Returns a DevilsAdvocateReport with challenges, non_yield_threshold,
        and recommendations.
        """
        # Try LLM-based challenge generation
        llm_challenges = self._llm_challenge(answer_human, evidence_nodes)

        if llm_challenges:
            challenges = llm_challenges
        else:
            challenges = self._deterministic_challenge(answer_human, answer_machine, evidence_nodes)

        # Compute non-yield threshold
        non_yield = self._compute_non_yield(challenges, answer_human)

        recommendations = self._generate_recommendations(challenges)

        return {
            "schema_version": self.schema_version,
            "answer_ref": answer_machine.get("query_id", ""),
            "challenges": challenges,
            "non_yield_threshold": round(non_yield, 3),
            "recommendations": recommendations,
        }

    def _llm_challenge(self, answer: str, evidence: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
        """Attempt LLM-based challenge generation."""
        evidence_text = ""
        if evidence:
            evidence_text = "\n".join(n.get("text", "")[:200] for n in evidence[:5])

        prompt = f"""You are a Devil's Advocate. Your job is to find WEAKNESSES in the following answer. Do NOT be agreeable. Challenge every claim.

Answer to challenge:
{answer[:2000]}

Available evidence:
{evidence_text}

For each weakness found, output a JSON array of objects:
[{{"challenge_type": "unverified_assumption|counter_evidence|scope_overreach|missing_perspective", "description": "...", "severity": "critical|major|minor", "evidence_against": "..."}}]

Find 2-5 weaknesses. Output ONLY the JSON array."""

        model_name = self.llm_model.replace("ollama/", "") if self.llm_model.startswith("ollama/") else self.llm_model
        from ..llm.provider import ollama_model_available
        if not ollama_model_available(model_name):
            logger.warning("Model %s not available locally; using deterministic fallback", model_name)
            return None
        try:
            result = subprocess.run(
                ["ollama", "run", model_name, prompt],
                capture_output=True, text=True, timeout=120,
                env={**os.environ, "OLLAMA_HOST": os.environ.get("OLLAMA_HOST", "http://localhost:11434")},
            )
            if result.returncode != 0:
                return None
            text = result.stdout.strip()
            json_start = text.find("[")
            json_end = text.rfind("]") + 1
            if json_start == -1:
                return None
            parsed = json.loads(text[json_start:json_end])
            if isinstance(parsed, list):
                return [c for c in parsed if c.get("challenge_type") in CHALLENGE_TYPES][:5]
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            pass
        return None

    def _deterministic_challenge(
        self, answer: str, answer_machine: Dict[str, Any], evidence: Optional[List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """Generate challenges using deterministic heuristics."""
        challenges = []
        evidence = evidence or []
        evidence_ids = {n.get("node_id", "") for n in evidence if n.get("node_id")}

        # 1. Unverified assumptions — sentences without citations
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', answer) if len(s.strip()) > 15]
        uncited = [s for s in sentences if not re.search(r'\([^)]*\d{4}[^)]*\)', s) and not re.search(r'\[citation', s)]
        if uncited:
            challenges.append({
                "challenge_type": "unverified_assumption",
                "description": f"{len(uncited)} statement(s) lack citation support",
                "severity": "major" if len(uncited) > len(sentences) * 0.4 else "minor",
                "evidence_against": uncited[0][:100],
            })

        # 2. Scope overreach — absolute claims without evidence
        absolute_patterns = [r'\ball\b', r'\bevery\b', r'\bnever\b', r'\balways\b', r'\bno\s+one\b', r'\bnone\b']
        for pat in absolute_patterns:
            matches = re.findall(pat, answer, re.IGNORECASE)
            if matches:
                challenges.append({
                    "challenge_type": "scope_overreach",
                    "description": f"Absolute claim found: '{pat}' appears {len(matches)} time(s)",
                    "severity": "minor" if len(matches) == 1 else "major",
                    "evidence_against": "Absolute claims require the strongest evidence.",
                })
                break

        # 3. Missing perspective — evidence not consulted
        if evidence and answer_machine.get("evidence"):
            cited_ids = {e.get("node_id", "") for e in answer_machine.get("evidence", [])}
            uncited_nodes = evidence_ids - cited_ids
            if uncited_nodes and len(uncited_nodes) > len(evidence_ids) * 0.3:
                challenges.append({
                    "challenge_type": "missing_perspective",
                    "description": f"{len(uncited_nodes)} evidence node(s) not cited in the answer",
                    "severity": "minor",
                    "evidence_against": "Consider incorporating more of the available evidence.",
                })

        # 4. Counter-evidence — hedging language suggests uncertainty
        hedging = ["may", "might", "could", "possibly", "it seems", "arguably"]
        hedge_count = sum(1 for h in hedging if h in answer.lower())
        if hedge_count >= 3:
            challenges.append({
                "challenge_type": "counter_evidence",
                "description": f"High hedging density ({hedge_count} hedging phrases) suggests the evidence may not fully support the claims",
                "severity": "minor",
                "evidence_against": "Hedging indicates the author is uncertain; verify the underlying evidence.",
            })

        return challenges[:5]

    @staticmethod
    def _compute_non_yield(challenges: List[Dict[str, Any]], answer: str) -> float:
        """Compute how well the answer addresses its own challenges.

        A high non-yield threshold means the answer is resilient.
        """
        if not challenges:
            return 1.0

        addressed = 0
        for c in challenges:
            # Simple heuristic: if the answer contains evidence keywords from the challenge
            desc = c.get("description", "").lower()
            severity = c.get("severity", "minor")

            # Minor challenges are considered "partially addressed" by default
            if severity == "minor":
                addressed += 0.5
            elif severity == "major":
                # Check if the answer addresses the concern
                if any(kw in answer.lower() for kw in desc.split()[:4]):
                    addressed += 0.3
            else:  # critical
                addressed += 0.0

        return addressed / len(challenges)

    @staticmethod
    def _generate_recommendations(challenges: List[Dict[str, Any]]) -> List[str]:
        """Generate actionable recommendations from challenges."""
        recs = []
        for c in challenges:
            ctype = c.get("challenge_type", "")
            if ctype == "unverified_assumption":
                recs.append("Add citations to support uncited claims.")
            elif ctype == "counter_evidence":
                recs.append("Strengthen claims with more definitive evidence or reduce hedging.")
            elif ctype == "scope_overreach":
                recs.append("Qualify absolute claims with scope limitations.")
            elif ctype == "missing_perspective":
                recs.append("Incorporate additional evidence nodes into the answer.")
        return list(set(recs))
