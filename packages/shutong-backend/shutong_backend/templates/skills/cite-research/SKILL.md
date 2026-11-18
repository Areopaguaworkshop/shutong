---
name: cite-research
description: Use when answering research questions from the local corpus. Provides BM25 search plus Merkle verification.
license: MIT
compatibility: shutong
---

# Cite-Research Skill

1. `shutong_search(query, top_k=20)`
2. `shutong_verify(csl_id, node_hash)` for quoted evidence
3. Discard FAIL nodes
4. Answer with Chicago citations