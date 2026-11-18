"""Shutong ingestion utilities — re-exports from citeindex.ingestion.deterministic.

Loads the deterministic module directly to avoid the broken dspy/litellm import
chain in citeindex's top-level __init__.
"""

from shutong_backend.ingestion.deterministic import (  # noqa: F401
    build_merkle_proof,
    build_merkle_tree,
    canonicalize_text,
    hash_payload,
    sha256_hex,
)