#!/usr/bin/env python3
"""Run the current Python BM25 pipeline for the parity query set.

This is a measurement baseline, not a reference answer key: the Python
tokenizer treats a contiguous Chinese run as one token.
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from shutong_backend.agents.chat import SearchPipeline


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default="../../corpus")
    parser.add_argument("--queries", default="test/fixtures/queries.json")
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    queries = json.loads(Path(args.queries).read_text(encoding="utf-8"))
    pipeline = SearchPipeline(corpus_root=args.corpus)
    payload = []
    for entry in queries:
        result = pipeline.search(entry["query"], top_k=args.top)
        hits = []
        for hit in result.get("results", []):
            hits.append(
                {
                    "node_id": hit.get("node_id"),
                    "source_id": hit.get("source_id"),
                    "page": hit.get("page"),
                    "score": hit.get("total_score"),
                }
            )
        payload.append(
            {
                "id": entry["id"],
                "language": entry["language"],
                "query": entry["query"],
                "status": result.get("status"),
                "retrieval_method": result.get("retrieval_method"),
                "hits": hits,
            }
        )
        print(
            f"{entry['id']} {entry['query']!r}: {result.get('status')} {len(hits)} hits",
            file=sys.stderr,
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
