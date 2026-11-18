#!/usr/bin/env python3
"""Generate golden vectors for the TypeScript Merkle/hash port.

Run from the package root with the Shutong backend virtualenv:

    PYTHONPATH=../shutong-backend ../shutong-backend/.venv/bin/python \
      scripts/generate-merkle-fixtures.py > test/fixtures/merkle-golden.json

The fixture file is committed so the TS tests do not need Python.
"""
from __future__ import annotations

import json

from shutong_backend.ingestion.deterministic import (
    build_merkle_proof,
    build_merkle_tree,
    canonicalize_text,
    hash_payload,
)


def canonical_json_dumps(value: object) -> str:
    """Same contract as citeindex.ingestion.deterministic.canonical_json_dumps."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

CANONICALIZE_INPUTS = [
    "  a\r\n\tb  ",
    "a\u00a0b",
    "a\u3000b",
    "a\x1cb",
    "a\n\nb",
    "",
    "  \t ",
]

JSON_INPUTS = [
    {"b": 2, "a": 1},
    {"unicode": "袁永甲", "nested": {"z": True, "y": None}, "arr": [1, "x", False]},
    {"😀": 1, "\ue000": 2},
    {"nested": [{"b": 2, "a": 1}, None, True]},
]

HASH_INPUTS = [
    "  a\r\n\tb  ",
    {"b": 2, "a": 1},
    {"unicode": "袁永甲", "nested": {"z": True, "y": None}},
]

MERKLE_CASES = [
    ["a", "b", "c", "d", "e"],
    ["aa", "bb"],
    [],
]

PROOF_CASES = [
    (["a", "b", "c", "d", "e"], 1),
    (["a", "b", "c", "d", "e"], 4),
    (["aa", "bb"], 0),
]


def main() -> None:
    fixtures = {
        "canonicalize": [
            {"input": value, "expected": canonicalize_text(value)}
            for value in CANONICALIZE_INPUTS
        ],
        "json": [
            {"input": value, "expected": canonical_json_dumps(value)}
            for value in JSON_INPUTS
        ],
        "hashPayload": [
            {"input": value, "expected": hash_payload(value)} for value in HASH_INPUTS
        ],
        "merkle": [
            {"leaves": leaves, "expected": build_merkle_tree(leaves)}
            for leaves in MERKLE_CASES
        ],
        "proof": [
            {
                "leaves": leaves,
                "leafIndex": index,
                "expected": build_merkle_proof(build_merkle_tree(leaves), index),
            }
            for leaves, index in PROOF_CASES
        ],
    }
    print(json.dumps(fixtures, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
