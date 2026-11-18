"""Outline Agent — generate hierarchical outlines from topics and corpus sources.

Takes a topic + corpus sources, produces a structured outline with
sections, subsections, and key claims mapped to evidence node IDs.
Uses Ollama for LLM-based outline generation with deterministic fallback.
"""

import json
import logging
import os
import subprocess
from typing import Any, Dict, List, Optional

from ..models import SCHEMA_VERSION

logger = logging.getLogger(__name__)


def _build_outline_prompt(topic: str, sources: List[str], scope: str) -> str:
    """Build the LLM prompt for outline generation."""
    source_list = "\n".join(f"- {s}" for s in sources[:20])
    return f"""Generate a structured academic outline for the topic: "{topic}"

Available sources:
{source_list}

Scope: {scope}

Requirements:
- Create 3-6 main sections, each with 2-4 subsections
- For each subsection, list 2-3 key claims that need evidence
- Assign a priority (high/medium/low) to each claim
- Output as JSON matching the WritingOutline schema
- Use Chicago author-date citation style for source references
- Each claim should be verifiable from the available sources

Output format:
{{
  "title": "...",
  "thesis": "One-sentence thesis statement",
  "scope": "...",
  "sections": [
    {{
      "heading": "...",
      "subsections": [
        {{
          "heading": "...",
          "key_claims": [
            {{"claim": "...", "priority": "high|medium|low", "source_hints": ["..."]}}
          ]
        }}
      ]
    }}
  ]
}}"""


class OutlineAgent:
    """Generate a hierarchical outline from a topic and corpus sources."""

    def __init__(self, schema_version: str = SCHEMA_VERSION, llm_model: str = "") -> None:
        self.schema_version = schema_version
        self.llm_model = llm_model or os.environ.get("SHUTONG_LLM_MODEL", "glm-5.3-flash:cloud")

    def generate(
        self,
        topic: str,
        sources: Optional[List[str]] = None,
        scope: str = "comprehensive",
    ) -> Dict[str, Any]:
        """Generate an outline for the given topic.

        Returns a dict with outline_id, title, thesis, scope, and sections.
        """
        import hashlib
        outline_id = f"outline-{hashlib.sha256(topic.encode()).hexdigest()[:8]}"
        sources = sources or []

        # Try LLM generation first
        outline = self._llm_generate(topic, sources, scope)
        if outline is None:
            # Fallback to deterministic outline
            outline = self._fallback_generate(topic, sources, scope)

        outline["outline_id"] = outline_id
        outline["schema_version"] = self.schema_version
        return outline

    def _llm_generate(self, topic: str, sources: List[str], scope: str) -> Optional[Dict[str, Any]]:
        """Attempt LLM-based outline generation via Ollama."""
        prompt = _build_outline_prompt(topic, sources, scope)
        model_name = self.llm_model.replace("ollama/", "") if self.llm_model.startswith("ollama/") else self.llm_model

        from ...llm.provider import ollama_model_available
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
                logger.warning("Ollama outline generation failed: %s", result.stderr[:200])
                return None

            # Extract JSON from the response
            text = result.stdout.strip()
            json_start = text.find("{")
            json_end = text.rfind("}") + 1
            if json_start == -1 or json_end == 0:
                logger.warning("No JSON found in LLM outline response")
                return None

            parsed = json.loads(text[json_start:json_end])
            if "sections" in parsed and isinstance(parsed["sections"], list):
                return parsed
            logger.warning("LLM outline missing 'sections' key")
            return None

        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
            logger.warning("LLM outline generation failed: %s", e)
            return None

    def _fallback_generate(self, topic: str, sources: List[str], scope: str) -> Dict[str, Any]:
        """Generate a deterministic outline structure as fallback."""
        sections = [
            {
                "heading": "Introduction",
                "subsections": [
                    {
                        "heading": f"Background and Context",
                        "key_claims": [
                            {"claim": f"The topic of {topic} has significant implications", "priority": "high", "source_hints": sources[:3]},
                            {"claim": "Current understanding requires further investigation", "priority": "medium", "source_hints": sources[3:6] if len(sources) > 3 else []},
                        ],
                    },
                    {
                        "heading": "Research Question",
                        "key_claims": [
                            {"claim": f"The central question concerns the nature and scope of {topic}", "priority": "high", "source_hints": []},
                        ],
                    },
                ],
            },
            {
                "heading": "Main Analysis",
                "subsections": [
                    {
                        "heading": "Primary Evidence",
                        "key_claims": [
                            {"claim": f"Key evidence supports the thesis regarding {topic}", "priority": "high", "source_hints": sources[:5]},
                        ],
                    },
                    {
                        "heading": "Counterarguments",
                        "key_claims": [
                            {"claim": "Alternative perspectives must be considered", "priority": "medium", "source_hints": sources[5:8] if len(sources) > 5 else []},
                        ],
                    },
                ],
            },
            {
                "heading": "Conclusion",
                "subsections": [
                    {
                        "heading": "Summary of Findings",
                        "key_claims": [
                            {"claim": f"The analysis demonstrates the significance of {topic}", "priority": "high", "source_hints": []},
                        ],
                    },
                ],
            },
        ]

        return {
            "title": f"Outline: {topic}",
            "thesis": f"This paper examines {topic}, analyzing its key dimensions and implications.",
            "scope": scope,
            "sections": sections,
        }
