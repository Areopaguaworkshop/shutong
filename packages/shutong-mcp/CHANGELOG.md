# Changelog

## 0.2.0

- Added scoped passage search with quote spans, context, edition metadata and
  Chicago citations. Topic retrieval can use local BGE-M3 alongside BM25.
  Quotation and seed searches can use Passim for related wording.
- Removed the public note and claim actions. Existing records remain on disk.
  Explicit DOCX export takes the caller's draft Markdown.
- Added a retrieval benchmark and a shared passage-mode entry point for the
  Python backend. Advanced retrieval requires local dependencies and model files.

## 0.1.1 — 2026-11-18

Packaging and CLI-metadata release. The MCP tool surface is unchanged.

### Fixed

- `shutong-mcp --version` printed a hardcoded `0.1.0`, and the MCP server
  advertised that version in its handshake. Both now read the version from
  `package.json` (`src/version.ts`), so they cannot drift from the release.
- `--help` and `-h` were not recognised and fell through to starting the stdio
  MCP server. They now print usage.
- The published 0.1.0 tarball had no `license` field even though the repository
  is MIT. `license` is now present, and `LICENSE` ships in the package.
- The 0.1.0 tarball omitted `CHANGELOG.md`, `CUTOVER.md` and `QUALITY.md`
  despite `files` listing them. All three are included again.
- Release metadata now matches the working tree, so the tarball can be
  reproduced from a tagged commit.

## 0.1.0 — 2026-11-18

First public TypeScript MCP server for Shutong.

### Added

- MCP stdio server for Node.js ≥24, built on `@modelcontextprotocol/server` v2.
- All 26 Shutong tools / 50 operations:
  - search, verify, corpus, citation
  - state, memory, status, paper status/audit/use/export
  - bibliography search/catalog and bibliography writes
  - source, note, claim, analysis
  - outreach, verifier report, ingest, ingest status, delete
- SQLite FTS5 search index over citeindex corpus artifacts.
  - contentless FTS5 index, BM25 ranking, regex search
  - paper/source scoping
  - derived and rebuildable; JSON/Merkle artifacts stay authoritative
- Merkle/hash contract compatible with `citeindex.ingestion.deterministic`.
- Note and claim writes with byte-compatible PyYAML frontmatter and note digests.
- TS-native Chicago author-date citation renderer (no citeproc-js dependency).
- DOCX export from verified claims.
- `shutong-mcp doctor` diagnostics.
- `shutong-mcp install` for OpenCode, Claude, Codex, Pi; Hermes instructions.
- `shutong-mcp rollback` with config backups and an install manifest.
- `npm run quality` gate:
  - Chinese hit@10: 20/20
  - English p50 Jaccard@10: 0.818
  - 26/26 tool registration
  - 280/280 Merkle roots
  - jieba/Intl token overlap: 0.913

### Requirements

- Node.js ≥24
- `citeindex` on PATH (latest compatible; no version pin)
- PyYAML for note frontmatter
- An LLM endpoint for local PDF metadata extraction

### Known limitations

- Chinese relevance labels are a regression baseline, not an independent
  human relevance study.
- Custom bibliography adapters (catalogue, OAI-PMH, publisher) are deferred.
- `@node-rs/jieba` is comparison-only; production uses `Intl.Segmenter`.
- Analysis spans use JavaScript UTF-16 offsets; astral Han spans may differ from
  Python.
- `npm publish` is manual; package output is prepared by `prepack`.
