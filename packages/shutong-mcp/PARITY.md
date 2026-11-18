# Search parity report

Measured on the 280-document / 98,664-node corpus against the current Python
BM25 pipeline (`agents.chat.SearchPipeline`, `top_k=10`), 50 queries
(`test/fixtures/queries.json`).

| Bucket | Queries | Mean Jaccard@10 | p50 | p10 | Zero overlap |
|---|---:|---:|---:|---:|---:|
| English | 25 | 0.712 | 0.818 | 0.25 | 1 |
| Chinese | 25 | 0.086 | 0.053 | 0 | 12 |
| Overall | 50 | 0.399 | 0.250 | 0 | 13 |

## Why Chinese parity fails

`shutong_backend/agents/indexing.py` uses:

```python
_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff\u3400-\u4dbf]+", re.UNICODE)
```

That matches a whole contiguous Han run as one token. `中国经济发展` is indexed
as one term, so a query for `中国` only matches documents where the exact token
`中国` appears alone. The TS FTS5 index segments with `Intl.Segmenter`, so the
two systems return different result sets by design.

Observed example: query `中国` returns 5 Python hits whose top result is a
Japanese “Chūgoku” reference; FTS5 returns the Chinese corpus passages about
中国. The Python output is not a quality reference for CJK.

## Revised acceptance

1. **English behavioral parity:** p50 Jaccard@10 ≥ 0.8. Current p50 is 0.818;
   mean is 0.712 because ranking differs on multi-term queries. Track mean as
   a trend, not a hard gate.
2. **Chinese quality:** use a labeled relevance set (expected source or node
   IDs per query) with recall@10 ≥ 0.8. Do not use the current Python BM25
   Chinese output as the oracle.
3. **Optional fair oracle:** a jieba-segmented Python baseline can be added
   later if exact cross-language ranking comparison is required. `jieba` is not
   currently installed in the Shutong backend venv.

## Reproduce

```bash
# Python baseline (slow: reloads the corpus per query)
PYTHONPATH=../shutong-backend ../shutong-backend/.venv/bin/python \
  scripts/python-bm25-baseline.py --corpus ../../corpus --top 10 \
  > test/fixtures/bm25-baseline.json

# TS index + Jaccard report
node scripts/parity.ts > /tmp/parity-report.json
```

`test/fixtures/bm25-baseline.json` is committed so the TS side can be compared
without a Python run.
