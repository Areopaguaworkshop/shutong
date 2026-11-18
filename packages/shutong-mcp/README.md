# @ephremyuan/shutong

TypeScript MCP server for Shutong: 26 tools for a local, citation-verified
scholarly corpus, backed by SQLite FTS5 and citeindex artifacts.

`citeindex` remains the only Python dependency, and only for ingestion.

## Install

```bash
npm install -g @ephremyuan/shutong
# or run without installing
npx @ephremyuan/shutong --help

# Prerequisites
pip install citeindex          # latest compatible; no version pin
shutong-mcp doctor
```

Requirements:

- Node.js ≥24
- `citeindex` on PATH (or `SHUTONG_CITEINDEX_BIN`)
- PyYAML (used for byte-compatible note frontmatter)
- an LLM endpoint for local PDF metadata extraction (`SHUTONG_LLM_MODEL`)

## Host setup

```bash
shutong-mcp install --host opencode
shutong-mcp install --host claude
shutong-mcp install --host codex
shutong-mcp install --host pi
```

Each install backs up the existing config and records it in
`~/.shutong/mcp-install.json`. Roll back with:

```bash
shutong-mcp rollback
```

Hermes is instruction-only:

```bash
shutong-mcp install --host hermes
```

See [CUTOVER.md](CUTOVER.md) for the host sequence.

## Tools

| Area | Tools |
|---|---|
| Research | `shutong_search`, `shutong_corpus`, `shutong_verify`, `shutong_status` |
| Citations | `shutong_citation`, `shutong_bibliography_search`, `shutong_bibliography_source_catalog` |
| State | `shutong_state_wake_up`, `shutong_state_snapshot`, `shutong_state_record_session`, `shutong_memory` |
| Paper | `shutong_paper_status`, `shutong_paper_audit`, `shutong_paper_use`, `shutong_paper_export_docx` |
| Bibliography/source writes | `shutong_bibliography`, `shutong_source` |
| Evidence | `shutong_note`, `shutong_claim`, `shutong_analysis` |
| Workspace | `shutong_workspace` |
| Outreach | `shutong_outreach`, `shutong_verifier_report` |
| Ingest | `shutong_ingest`, `shutong_ingest_status`, `shutong_delete_document` |

`citation.render` is a TS-native Chicago author-date formatter, not citeproc-js.
`shutong_analysis` covers concordance, collocations, quotation, text reuse and
digest-bound contextual-sentiment records.

## Search

The search index is a derived SQLite database:

- `sources` — one row per citeindex record
- `nodes` — searchable nodes, original text plus segmented tokens
- `nodes_fts` — contentless FTS5 index, `rowid = nodes.id`
- `index_meta` — schema version, corpus hash, build timestamp

Measured on the current 280-document / 98,664-node corpus:

| Metric | Result |
|---|---:|
| Build | 6.4 s |
| Database | 128.9 MB |
| BM25 query | 0.5–4.7 ms |
| Regex scan | ~200 ms |

The index is rebuilt from artifacts and can be deleted at any time. Citeindex
JSON and Merkle artifacts remain the source of truth.

## Quality

```bash
npm run quality
```

| Gate | Result |
|---|---|
| Chinese hit@10 | 20/20 |
| English p50 Jaccard@10 vs Python BM25 | 0.818 |
| Tool registration | 26/26 |
| Merkle roots | 280/280 |
| Jieba/Intl token overlap | 0.913 |

See [QUALITY.md](QUALITY.md) for caveats, including the regression-baseline
status of the Chinese labels.

## Configuration

| Variable | Purpose |
|---|---|
| `SHUTONG_CORPUS_ROOT` | corpus root (default `corpus`) |
| `SHUTONG_STORAGE_DIR` | `.shutong` state directory |
| `SHUTONG_INDEX_DB` | SQLite path (default `<storage>/search.sqlite`) |
| `SHUTONG_SKIP_INDEX=1` | open an existing index without rebuilding |
| `SHUTONG_CITEINDEX_BIN` | override the citeindex CLI |
| `SHUTONG_LLM_MODEL` | provider-qualified model passed to ingest |
| `SHUTONG_PYTHON` | Python used for note frontmatter serialization |

## Development

```bash
npm test
npm run typecheck
npm run build
npm run quality
npm pack --dry-run
```

`prepack` rebuilds `dist/`; the tarball contains `dist/`, `tools.generated.json`,
`README.md`, `CHANGELOG.md`, `CUTOVER.md`, `QUALITY.md` and `LICENSE`.

## Known limitations

- Chinese relevance labels are a regression baseline, not an independent study.
- Custom bibliography adapters (catalogue, OAI-PMH, publisher) are deferred.
- `@node-rs/jieba` is comparison-only; production uses `Intl.Segmenter`.
- Analysis uses JavaScript UTF-16 offsets; astral Han spans may differ from Python.
- Note frontmatter uses PyYAML for byte-identical digests.

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## License

MIT
