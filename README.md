# Shutong 書童

**An academic-research application for coding agents — backend-as-agent via MCP**

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License: MIT">
</p>

---

## What Shutong does

Shutong helps a host agent discover scholarly sources, ingest approved material,
and retrieve passages with edition-specific Chicago author-date citations.
The host uses those passages to answer questions and can export a requested draft
to DOCX. Workspace scope, corpus integrity checks, and session state live locally.

## Architecture

```text
Host agent and project skills
  ├─ Python backend over MCP or DeepSeek Harness RPC
  │    └─ Passage mode calls the installed shutong-mcp executable
  └─ Standalone TypeScript MCP server
       ├─ CiteIndex intake → corpus text, CSL metadata and Merkle artifacts
       ├─ SQLite FTS5 → scoped passage retrieval
       └─ Optional local Passim and BGE-M3 → text parallels and semantic matches
```

Python also provides corpus intake, workspace operations, and legacy keyword and
regex retrieval. The host owns the session and answer synthesis.

### Host adapters

| Host | MCP registration | Agent definitions | Skills | Session instructions |
|------|------------------|--------|--------|-------------------------|
| **OpenCode** | `opencode.json` `mcp.servers.shutong` | none | `.agents/skills/*/SKILL.md` | `AGENTS.md` |
| **Claude Code** | `.mcp.json` | none | `.claude/skills/*/SKILL.md` | `CLAUDE.md` |
| **Codex** | `.codex/config.toml` `[mcp_servers.shutong]` | none | `.codex/skills/*/SKILL.md` | `AGENTS.md` |
| **Pi** | `.pi/mcp.json` `mcpServers.shutong` | none | `.pi/skills/*/SKILL.md` | host instructions |
| **DeepSeek Harness** | `adapters/deepseek-harness/shutong.ts` | none | plugin `ctx.systemPrompt` | plugin `agent.inject()` |

Shutong ships no agent definitions. A host keeps its own agent runtime; Shutong
supplies the MCP server, the skill pack, and the routing rules in `AGENTS.md`.

See `adapters/README.md` for details. OMP (oh-my-pi) can connect through its
documented `mcpServers` config; use the host's own config rather than a Shutong
agent definition. Hermes receives a manual MCP configuration note.

---

## Quick Start

### Prerequisites

```bash
# Create or verify one local backend environment shared by Shutong projects.
shutong setup

# Optional local LLM for legacy outline/draft/review tools.
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull qwen3.5:cloud              # primary model
```

> **GROBID** (PDF structure extraction) is handled inside the `citeindex` project, not here — no action needed in this repo.

### Install the TypeScript MCP server (optional)

```bash
npm install -g @ephremyuan/shutong
shutong-mcp install --host opencode
```

`@ephremyuan/shutong` is the standalone Node.js MCP server (Node ≥24) with a
local SQLite FTS5 index and its own host installers. It exposes the same 24-tool
surface as the Python backend and is the cutover target described in
[packages/shutong-mcp/CUTOVER.md](packages/shutong-mcp/CUTOVER.md); rollback is
`shutong-mcp rollback`. Package details:
[packages/shutong-mcp/README.md](packages/shutong-mcp/README.md).

### Diagnose setup

```bash
packages/shutong-backend/.venv/bin/python -m shutong_backend.cli doctor
```

### Use it inside a host

You don't run Shutong as a standalone app — you connect it to an agent host and ask in natural language.

**OpenCode** (already wired):
```bash
opencode
```

**Claude Code**:
```bash
claude
```

**Codex**:
```bash
codex
```

**DeepSeek Harness** — load `adapters/deepseek-harness/shutong.ts` as a plugin (dev-preview; verify against installed Cordis version).

Shutong auto-loads the project instructions, calls `shutong_state_wake_up` at
session start, confirms the active work, and routes only necessary tasks to
Workspace Planner, Bibliographer, Ingestor, and Verifier.

### The workflow, step by step

1. Confirm the work and choose the source scope.
2. Discover sources, approve access and ingest them.
3. Use `shutong_search` in passage mode to retrieve cited text for a question,
   quotation or parallel passage.
4. If requested, draft from the cited passages and export the supplied Markdown
   with `shutong_paper_export_docx`.

See the [passage-search setup](packages/shutong-mcp/README.md#passage-search)
for Passim, BGE-M3 and scoped requests.

## Architecture implementation status

The active contract is [the architecture brief](docs/archetecture-2026-08-29.md)
and its [implementation plan](docs/plans/2026-08-29-paper-scoped-scholar-agent-plan.md).
These documents describe the earlier paper-scoped architecture. The current passage search contract is documented below.

| Area | Status |
|---|---|
| Paper/work scope, approvals, source intake and local DOCX export | Implemented and covered by paper-model tests. |
| Shutong conductor plus Bibliographer, Ingestor, Verifier, and Workspace Planner | Rendered for Codex, OpenCode, and Claude Code; host-renderer tests cover the generated files. |
| Public metadata discovery | Crossref, OpenAlex, Semantic Scholar, DOAJ, Open Library, plus scholar-supplied HTTPS catalogue, OAI-PMH, and publisher metadata endpoints. |
| First-run backend setup | `shutong setup` creates a per-user virtual environment and installs the bundled backend; package contents are checked with `npm pack --dry-run`. |
| Full plan parity | Not yet complete: adapter health/rate policies and frozen parser fixtures, enforced 30–50 annotated bibliography screening, independent bibliography verification, and a single cross-host end-to-end evidence-artifact fixture remain outstanding. |

### Paper-scoped research

Create a paper workspace, add only the sources it may use, and activate it:

```bash
bun run shutong -- paper create nicea --title "Nicaea" --question "How did doctrine develop?"
bun run shutong -- paper add-source nicea athanasius-de-incarnation --role primary
bun run shutong -- paper use nicea
bun run shutong -- paper audit
```

An active paper scopes searches to its source set. To retrieve cited passages
through either MCP server, call `shutong_search` with:

```json
{"mode":"passages","intent":"topic","query":"How do these authors describe hospitality?","top_k":10}
```

Use `intent: "quotation"` with wording to locate or `intent: "parallel"` with
wording or a seed passage ID. The result includes original text, a locator, a
citation, and match details. A discovered bibliography record becomes searchable
after ingestion and indexing. For a running TypeScript MCP server, restart the
server after ingestion so the default index rebuild sees the new source.

---

## CLI Commands

### Python backend CLI (setup/maintenance)

```bash
python -m shutong_backend.cli init       # scaffold a project layer
python -m shutong_backend.cli sync       # refresh AGENTS.md corpus snapshot
python -m shutong_backend.cli install    # write global Scholar Principle
python -m shutong_backend.cli doctor     # diagnose setup
```

### Bun launcher (project scaffolding)

```bash
bun run shutong -- init         # create native .shutong project scaffolding
bun run shutong -- paper        # create, activate, audit, or assign sources to a paper
bun run shutong -- doctor       # diagnose launcher, backend, Ollama, and corpus health
bun run shutong -- status       # show engine status
```

---

## 24 MCP Tools

| Category | Tool | Description |
|----------|------|-------------|
| **State** | `shutong_state_wake_up` | cross-session context (passport + diary + graph) for session start |
| **State** | `shutong_state_snapshot` | unified snapshot of all research state |
| **State** | `shutong_state_record_session` | record a session across diary + passport |
| **Status** | `shutong_status` | corpus health + integrity + research state in one call |
| Research | `shutong_search` | keyword, regex, or ranked cited passages (`mode`) |
| Research | `shutong_verify` | node or whole-corpus Merkle verification (`mode`) |
| Bibliography | `shutong_bibliography_search` | public scholarly metadata search |
| Bibliography | `shutong_bibliography_source_catalog` | available source adapters and access classes |
| Ingest | `shutong_ingest` | ingest PDF/URL/DJVU/media into corpus |
| Ingest | `shutong_ingest_status` | check ingestion progress |
| Ingest | `shutong_delete_document` | remove document from corpus |
| Paper | `shutong_paper_use`, `shutong_paper_status`, `shutong_paper_audit`, `shutong_paper_export_docx` | activation, gates, status, and export |
| Workspace | `shutong_workspace` | `create_paper`, `create_project`, `create_work`, `list`, `plan_switch`, `activate` |
| Corpus | `shutong_corpus`, `shutong_citation` | corpus state and citation operations |
| Memory | `shutong_memory` | search, list, and save research memory |
| Outreach | `shutong_outreach` | record public contact or draft unsent outreach |
| Verification | `shutong_verifier_report` | record or scholar-override evidence reports |

---

## Project Layout

```
shutong/
├── AGENTS.md                    # Scholar Principle + research protocols (OpenCode/Codex)
├── CLAUDE.md                    # same, for Claude Code
├── opencode.json                # OpenCode MCP config
├── .mcp.json                    # Claude Code MCP config
├── .claude/                     # Claude Code commands + skills
├── .codex/                      # Codex config + skills
├── .opencode/                   # OpenCode commands
├── .shutong/                    # local paper data, glossary, and compatibility artifacts
├── adapters/                    # DeepSeek Harness plugin + adapter README
├── packages/shutong-backend/    # Python backend (the agent)
│   ├── shutong_backend/
│   │   ├── mcp_server.py        # MCP tool surface (24 tools)
│   │   ├── rpc_server.py        # NDJSON RPC surface
│   │   ├── agents/              # pipeline, chat, writing, review, memory
│   │   ├── state.py             # unified research state facade
│   │   └── tools/               # research, ingest, verify, corpus, bibliography
│   └── tests/
├── shutong/                     # Bun launcher (scaffolding CLI)
├── scripts/                     # standalone ingest/export/search helpers
├── corpus/                      # digitalized, indexed source derivatives
├── library/                     # preserved original source files
└── papers/                      # paper manifests, drafts, and notes
```

---

## Design rules

- **Separate discovery and corpus search.** Bibliography discovery returns
  candidate metadata. CiteIndex intake creates the artifacts used for retrieval.
- **Inspect the original text.** Use passage locators and Merkle integrity
  checks before quoting. Cite the source edition used by the passage.
- **Keep advanced retrieval optional.** Passim and BGE-M3 require local setup.
  Search reports unavailable methods and can return exact or BM25 results.
- **Cite from retrieval.** The public workflow uses located corpus passages.
  Existing notes and claims remain available on disk.

## Development

```bash
# Python backend tests
cd packages/shutong-backend
.venv/bin/python -m pytest -q

# Bun launcher typecheck
bun run --cwd shutong typecheck
```

## License

MIT License
