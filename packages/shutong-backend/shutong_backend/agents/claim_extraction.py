"""Enhanced Claim Extraction — semantic and rule-based claim detection.

Provides both rule-based (fast, deterministic) and optional LLM-based
(semantic) claim extraction with typed claims and structured output.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from .models import SCHEMA_VERSION
from .v12_runtime import main as _v12_main

logger = logging.getLogger(__name__)


@dataclass
class ClaimExtractionOutput:
    """Structured output from enhanced claim extraction."""
    schema_version: str = SCHEMA_VERSION
    claims: List[Dict[str, Any]] = field(default_factory=list)
    total_claims: int = 0
    claim_types: Dict[str, int] = field(default_factory=dict)
    extraction_method: str = "rule_based"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Claim type classification ────────────────────────────────────────

CLAIM_TYPE_PATTERNS = {
    "statistical": [
        r"\b\d+\.?\d*\s*%", r"\b\d+\.?\d*\s*(times|fold|percent|per\s*cent)\b",
        r"\b(correlation|significant|p-value|confidence\s*interval)\b",
    ],
    "definition": [
        r"\b(is defined as|refers to|is known as|means|denotes)\b",
        r"\b(is a |are a |is an |are an )\b.*\b(that|which|who)\b",
    ],
    "argument": [
        r"\b(therefore|thus|hence|consequently|it follows)\b",
        r"\b(we argue|we claim|we propose|we suggest)\b",
        r"\b(should|ought to|must|need to)\b",
    ],
    "opinion": [
        r"\b(I believe|I think|in my view|arguably|perhaps|seemingly)\b",
        r"\b(importantly|interestingly|notably|surprisingly)\b",
    ],
}


def classify_claim_type(text: str) -> str:
    """Classify a claim into factual/definition/argument/opinion/statistical."""
    lower = text.lower()
    scores: Dict[str, int] = {}
    for claim_type, patterns in CLAIM_TYPE_PATTERNS.items():
        score = sum(1 for p in patterns if re.search(p, lower))
        if score > 0:
            scores[claim_type] = score
    if scores:
        return max(scores, key=scores.get)
    return "factual"


# ── Entity extraction ────────────────────────────────────────────────

def extract_entities(text: str) -> List[str]:
    """Extract named entities from text."""
    # Proper nouns (multi-word capitalized sequences)
    proper_nouns = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", text)
    # Acronyms
    acronyms = re.findall(r"\b[A-Z]{2,}\b", text)
    # Technical terms in quotes
    quoted = re.findall(r'["“]([^"”]+)["”]', text)
    return sorted(set(proper_nouns + acronyms + quoted))


# ── Rule-based extraction ────────────────────────────────────────────

def extract_claims_rule_based(text: str, section_ref: str = "", hierarchy_path: str = "/") -> List[Dict[str, Any]]:
    """Extract claims using rule-based sentence splitting and classification."""
    claims = []
    # Split into sentences
    sentences = re.split(r"(?<=[.!?])\s+", text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 20]

    for idx, sentence in enumerate(sentences[:30], start=1):
        claim_type = classify_claim_type(sentence)
        entities = extract_entities(sentence)
        # Detect polarity
        polarity = "neutral"
        if re.search(r"\b(not|no|never|none|nobody|nothing|neither|nowhere)\b", sentence, re.IGNORECASE):
            polarity = "negative"
        elif re.search(r"\b(always|all|every|must|certainly|definitely)\b", sentence, re.IGNORECASE):
            polarity = "positive"

        claims.append({
            "claim_id": f"claim-{idx}",
            "claim_text": sentence,
            "claim_type": claim_type,
            "section_ref": section_ref,
            "verbatim_passage": sentence,
            "polarity_tag": polarity,
            "entities": entities,
            "hierarchy_path": hierarchy_path,
        })
    return claims


# ── LLM-based extraction ─────────────────────────────────────────────

def extract_claims_llm(text: str, llm_model: str = "", section_ref: str = "", hierarchy_path: str = "/") -> List[Dict[str, Any]]:
    """Extract claims using LLM for semantic detection. Falls back to rule-based on failure."""
    llm_model = llm_model or os.environ.get("SHUTONG_LLM_MODEL", "glm-5.3-flash:cloud")

    prompt = f"""Analyze the following text and extract distinct claims. For each claim, identify:
1. claim_text: the exact claim statement
2. claim_type: one of (factual, definition, argument, opinion, statistical)
3. polarity: positive, negative, or neutral
4. entities: key named entities mentioned

Text:
{text[:3000]}

Respond in JSON format as a list of objects with keys: claim_text, claim_type, polarity, entities"""

    try:
        import ollama
        client = ollama.Client()
        response = client.chat(
            model=llm_model,
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.get("message", {}).get("content", "")
        # Try to parse JSON from the response
        json_match = re.search(r"\[.*\]", content, re.DOTALL)
        if json_match:
            raw_claims = json.loads(json_match.group())
            claims = []
            for idx, rc in enumerate(raw_claims[:30], start=1):
                claim_text = rc.get("claim_text", "")
                if not claim_text or len(claim_text) < 10:
                    continue
                claims.append({
                    "claim_id": f"claim-{idx}",
                    "claim_text": claim_text,
                    "claim_type": rc.get("claim_type", "factual"),
                    "section_ref": section_ref,
                    "verbatim_passage": claim_text,
                    "polarity_tag": rc.get("polarity", "neutral"),
                    "entities": rc.get("entities", []),
                    "hierarchy_path": hierarchy_path,
                })
            return claims
    except Exception as e:
        logger.warning("LLM claim extraction failed, falling back to rule-based: %s", e)

    # Fallback to rule-based
    return extract_claims_rule_based(text, section_ref, hierarchy_path)


# ── Main extraction API ──────────────────────────────────────────────

def extract_claims(
    text: str,
    section_ref: str = "",
    hierarchy_path: str = "/",
    llm_model: str = "",
    use_llm: bool = False,
) -> ClaimExtractionOutput:
    """Extract claims from text with optional LLM enhancement.

    Args:
        text: Input text to extract claims from
        section_ref: Section reference label
        hierarchy_path: Document hierarchy path
        llm_model: Ollama model to use for LLM extraction
        use_llm: Whether to use LLM-based extraction (falls back to rule-based on failure)

    Returns:
        ClaimExtractionOutput with structured claims and metadata
    """
    if use_llm:
        claims = extract_claims_llm(text, llm_model, section_ref, hierarchy_path)
        method = "llm_enhanced"
    else:
        claims = extract_claims_rule_based(text, section_ref, hierarchy_path)
        method = "rule_based"

    # Compute claim type counts
    type_counts: Dict[str, int] = {}
    for c in claims:
        ct = c.get("claim_type", "factual")
        type_counts[ct] = type_counts.get(ct, 0) + 1

    return ClaimExtractionOutput(
        claims=claims,
        total_claims=len(claims),
        claim_types=type_counts,
        extraction_method=method,
    )


# ── V12 adapter ──────────────────────────────────────────────────────

if __name__ == "__main__":
    _v12_main("ClaimExtractionAgent")
