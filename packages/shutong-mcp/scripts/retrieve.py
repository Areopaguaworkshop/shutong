"""Local Passim and BGE-M3 adapters for the passage search tool."""

import hashlib
import heapq
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


def passim_matches(request):
    if not request["passages"]:
        return []
    records = [{"id": "query", "is_seed": True, "text": request["query"]}]
    records.extend(
        {"id": str(row["id"]), "is_seed": False, "text": row["text"]}
        for row in request["passages"]
    )
    text = {row["id"]: row["text"] for row in records}
    Path("passim-input.json").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.setdefault("SPARK_SUBMIT_ARGS", "--master local[2]")
    with Path("passim.log").open("w") as log:
        subprocess.run(
            [os.environ.get("SHUTONG_PASSIM_BIN", "passim"),
             "--fields", "is_seed", "--filterpairs", "is_seed AND NOT is_seed2",
             "--floating-ngrams", "-n", "13", "-m", "3", "-a", "24",
             "passim-input.json", "passim-output"],
            env=env, stdout=log, stderr=log, check=True, timeout=270,
        )
    parts = sorted(Path("passim-output/out.json").glob("part-*"))
    if not parts:
        raise RuntimeError("Passim did not produce cluster output")
    groups = {}
    for part in parts:
        for line in part.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            key = str(row["id"])
            start, end = row["begin"], row["end"]
            if key in text and 0 <= start < end <= len(text[key]):
                groups.setdefault(row["cluster"], []).append((key, start, end))

    matches = []
    for group in groups.values():
        seeds = [(start, end) for key, start, end in group if key == "query"]
        if not seeds:
            continue
        seed_start, seed_end = max(seeds, key=lambda pair: pair[1] - pair[0])
        for key, start, end in group:
            if key == "query":
                continue
            matches.append({
                "id": int(key),
                "start": utf16_offset(text[key], start),
                "end": utf16_offset(text[key], end),
                "seed_start": utf16_offset(text["query"], seed_start),
                "seed_end": utf16_offset(text["query"], seed_end),
                "score": min(end - start, seed_end - seed_start),
            })
    return sorted(matches, key=lambda row: (-row["score"], row["id"]))


def utf16_offset(text, offset):
    return len(text[:offset].encode("utf-16-le")) // 2


def semantic_matches(request, cache_path):
    model_path = os.environ["SHUTONG_BGE_MODEL"]
    if not Path(model_path).is_dir():
        raise ValueError("SHUTONG_BGE_MODEL must point to a local model directory")
    from FlagEmbedding import BGEM3FlagModel
    import numpy as np
    revision = os.environ.get("SHUTONG_BGE_REVISION")
    if not revision:
        raise ValueError("Set SHUTONG_BGE_REVISION to the installed model revision")
    model = BGEM3FlagModel(model_path, use_fp16=False)
    query = model.encode_queries([request["query"]], max_length=1024)["dense_vecs"][0]
    cache_key = json.dumps([model_path, revision, "dense-1024-v1"])
    Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
    ranked = []
    with sqlite3.connect(cache_path, timeout=30) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS embeddings (
            model TEXT, text_hash TEXT, vector BLOB NOT NULL,
            PRIMARY KEY (model, text_hash)
        )""")
        for offset in range(0, len(request["passages"]), 32):
            batch = request["passages"][offset:offset + 32]
            rows = [(row, hashlib.sha256(row["text"].encode()).hexdigest()) for row in batch]
            vectors = {}
            missing = {}
            for row, digest in rows:
                cached = db.execute(
                    "SELECT vector FROM embeddings WHERE model=? AND text_hash=?",
                    (cache_key, digest),
                ).fetchone()
                if cached is None:
                    missing[digest] = row["text"]
                else:
                    vectors[digest] = np.frombuffer(cached[0], dtype="<f4")
            if missing:
                encoded = model.encode_corpus(list(missing.values()), batch_size=32, max_length=1024)["dense_vecs"]
                for digest, vector in zip(missing, encoded, strict=True):
                    vectors[digest] = vector.astype("<f4")
                with db:
                    db.executemany(
                        "INSERT OR IGNORE INTO embeddings VALUES (?, ?, ?)",
                        [(cache_key, key, vectors[key].tobytes()) for key in missing],
                    )
            for row, digest in rows:
                score = float(np.dot(query, vectors[digest]))
                if not np.isfinite(score):
                    continue
                entry = (score, -row["id"])
                if len(ranked) < request["limit"]:
                    heapq.heappush(ranked, entry)
                else:
                    heapq.heappushpop(ranked, entry)
    return [{"id": -row_id, "score": score} for score, row_id in sorted(ranked, reverse=True)]


if __name__ == "__main__":
    method, input_file, output_file, cache_path = sys.argv[1:]
    request = json.loads(Path(input_file).read_text(encoding="utf-8"))
    results = passim_matches(request) if method == "passim" else semantic_matches(request, cache_path)
    Path(output_file).write_text(json.dumps(results[:request["limit"]]), encoding="utf-8")
