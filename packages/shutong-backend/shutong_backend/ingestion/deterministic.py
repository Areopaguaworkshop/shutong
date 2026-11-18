"""Deterministic hash and Merkle utilities — re-exported from citeindex.

Loads citeindex.ingestion.deterministic directly via importlib to bypass
the broken dspy/litellm import chain in citeindex's top-level __init__.
"""

import importlib.util
import os


def _find_deterministic_path() -> str:
    """Locate citeindex/ingestion/deterministic.py on disk without importing citeindex."""
    spec = importlib.util.find_spec("citeindex")
    if spec is None or not spec.submodule_search_locations:
        raise ImportError("citeindex package not found — ensure it is installed")
    ci_dir = next(iter(spec.submodule_search_locations))
    path = os.path.join(ci_dir, "ingestion", "deterministic.py")
    if os.path.exists(path):
        return path
    raise ImportError(f"citeindex.ingestion.deterministic not found at {path}")


def _load_deterministic():
    """Load citeindex.ingestion.deterministic bypassing broken __init__."""
    # Try normal import first (works if dspy dependency is healthy)
    try:
        from citeindex.ingestion.deterministic import (  # type: ignore[no-redef]
            build_merkle_proof,
            build_merkle_tree,
            canonicalize_text,
            hash_payload,
            sha256_hex,
        )
        return build_merkle_proof, build_merkle_tree, canonicalize_text, hash_payload, sha256_hex
    except ImportError:
        pass

    # Direct file load — bypasses citeindex.__init__ which triggers dspy
    path = _find_deterministic_path()
    spec = importlib.util.spec_from_file_location("citeindex.ingestion.deterministic", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return (
        mod.build_merkle_proof,
        mod.build_merkle_tree,
        mod.canonicalize_text,
        mod.hash_payload,
        mod.sha256_hex,
    )


_funcs = _load_deterministic()
build_merkle_proof = _funcs[0]
build_merkle_tree = _funcs[1]
canonicalize_text = _funcs[2]
hash_payload = _funcs[3]
sha256_hex = _funcs[4]

__all__ = [
    "build_merkle_proof",
    "build_merkle_tree",
    "canonicalize_text",
    "hash_payload",
    "sha256_hex",
]