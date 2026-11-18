# Quality gate

Run:

```bash
npm run quality
```

The gate exits non-zero if any criterion fails.

## Result on the current corpus

| Gate | Result |
|---|---|
| Chinese hit@10 | 20 / 20 queries |
| Chinese mean source recall@10 | 1.00 |
| English Jaccard@10 p50 vs Python BM25 | 0.818 |
| Tool registration | 26 / 26 definitions |
| Merkle roots | 280 / 280, 0 mismatches |
| Jieba vs Intl token overlap | 0.913 mean |

## Caveats

- The Chinese labels are seeded from the current top results and act as a
  **regression baseline**, not an independent human relevance study. An
  independent labeled set is still a quality task.
- Jieba is comparison-only. Production indexing still uses `Intl.Segmenter`;
  adopting jieba requires rebuilding the index and re-running this gate.
- Custom bibliography adapters (catalogue, OAI-PMH, publisher) remain deferred
  and are not part of the pass criteria.
- Analysis uses JavaScript UTF-16 offsets; astral Han spans can differ from the
  Python implementation.
- Note frontmatter uses a PyYAML shim for byte-identical note digests.
