# Shutong 書童

**An academic-research application for coding agents — backend-as-agent via MCP**

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License: MIT">
</p>

---

## Why This Exists

Large Language Models write fluently but **cannot cite their sources**. When an LLM tells you about a study, a historical event, or a legal precedent, there is no way to verify the claim, trace it back to a page, or reproduce the evidence chain. For scholars, this makes LLM output fundamentally unusable in serious work.

**Shutong is a host-agnostic academic-research application.** Its Python backend is the agent — it owns the research pipeline, cross-session state, and Merkle-verified integrity. Any coding agent (OpenCode, Claude Code, Codex, DeepSeek Harness) connects to it over MCP and becomes a citation-safe research assistant.

### What Shutong does for researchers

- **Ingests any source** — PDFs (digital or scanned), URLs, DJVU, EPUB, DOCX, video/audio — into a structured, hash-verified corpus via [citeindex](https://pypi.org/project/citeindex/).
- **Answers questions** with Chicago author-date citations, where every inline reference traces to a specific passage in your documents.
- **Eliminates hallucination** by design: BM25 deterministic retrieval, mandatory evidence-to-claim mapping, and fail-closed Merkle integrity verification.
- **Enforces paper evidence gates** — approved bibliography → ingested source → verified note → verified claim → explicit draft.
- **Persists cross-session state locally** — research passports, knowledge graph, session diary, and memory, auto-injected at session start without sending paper content or notes to external services.
- **Supports host-agent EN→ZH-Simplified translation** while preserving citations and established theological terminology.

---

## Architecture

Shutong is **backend-as-agent**. The Python backend owns the workflow, state, and enforcement; the host is just transport + UI. The universal contract is MCP, so the same backend serves every host.

```
Host (OpenCode / Claude Code / Codex / DeepSeek Harness)
        │  MCP (or NDJSON RPC for DeepSeek Harness)
        ▼
Python backend = THE AGENT
  ├── workspace planner  — proposes project/work changes; scholar confirms
  ├── Shutong conductor  — confirmed work, specialist routing, and evidence gates
  ├── shutong_state_*    — cross-session state (wake_up / snapshot / record_session)
  ├── shutong_status     — corpus + integrity + state visibility
  └── domain tools       — search / verify / ingest / translate / paper / memory
```

### Host adapters

| Host | MCP registration | Agents | Skills | Session-start injection |
|------|------------------|--------|--------|-------------------------|
| **OpenCode** | `opencode.json` `mcp.shutong` | none | `.agents/skills/*/SKILL.md` | `AGENTS.md` (auto-load) |
| **Claude Code** | `.mcp.json` | none | `.claude/commands/*.md`, `.agents/skills` | `CLAUDE.md` (auto-load) |
| **Codex** | `.codex/config.toml` `[mcp_servers.shutong]` | none | `.codex/skills/*/SKILL.md` | `AGENTS.md` (auto-load) |
| **DeepSeek Harness** | `adapters/deepseek-harness/shutong.ts` | none | plugin `ctx.systemPrompt` | plugin `agent.inject()` |

Shutong ships no agent definitions. A host keeps its own agent runtime; Shutong
supplies the MCP server, the skill pack, and the routing rules in `AGENTS.md`.

See `adapters/README.md` for details. **Hermes and Pi** are not identifiable as coding-agent CLIs in the 2026 ecosystem — provide a repo/URL to add their adapters.

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
Workspace Planner, Bibliographer, Ingestor, Noter, and Verifier.

### The workflow, step by step

```
1. Confirm work        shutong_workspace(action: plan_switch) → scholar confirmation
2. Discover            Bibliographer saves an annotated bibliography shortlist
3. Approve + ingest    scholar approval → authorized source intake
4. Read and note       Noter creates source-located notes
5. Verify              Verifier checks notes and claim-evidence links
6. Draft               explicit scholar request, verified claims only
7. Export              shutong_paper_export_docx
```

The enforced lineage is `approved bibliography → ingested source → verified
note → verified claim → explicit draft`. A missing link blocks drafting and
identifies the next scholar action.

For collocations, contextual sentiment, quotation checks and source text reuse,
see the [evidence analysis workflow](docs/evidence-analysis.md). Four skills
extend the existing roles; the main agent writes requested reports and short
cited syntheses from verified evidence. Analysis-linked notes also require a
current passing analysis review.

## Architecture implementation status

The active contract is [the architecture brief](docs/archetecture-2026-08-29.md)
and its [implementation plan](docs/plans/2026-08-29-paper-scoped-scholar-agent-plan.md).
The legacy documents formerly under `docs/` are retired.

| Area | Status |
|---|---|
| Paper/work boundaries, approvals, source intake, notes, claims, audit gate, and local DOCX export | Implemented and covered by paper-model tests. |
| Shutong conductor plus Bibliographer, Noter, Ingestor, Verifier, and Workspace Planner | Rendered for Codex, OpenCode, and Claude Code; host-renderer tests cover the generated files. |
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

An active paper restricts `shutong_search` and regex search to its approved sources. Paper workspaces store metadata, source approvals, notes, and audit state locally; retrieval and drafting fail closed when the evidence lineage is incomplete.

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

## 25 MCP Tools

| Category | Tool | Description |
|----------|------|-------------|
| **State** | `shutong_state_wake_up` | cross-session context (passport + diary + graph) for session start |
| **State** | `shutong_state_snapshot` | unified snapshot of all research state |
| **State** | `shutong_state_record_session` | record a session across diary + passport |
| **Status** | `shutong_status` | corpus health + integrity + research state in one call |
| Research | `shutong_search` | keyword or regex corpus search (`mode`) |
| Research | `shutong_verify` | node or whole-corpus Merkle verification (`mode`) |
| Bibliography | `shutong_bibliography_search` | public scholarly metadata search |
| Bibliography | `shutong_bibliography_source_catalog` | available source adapters and access classes |
| Ingest | `shutong_ingest` | ingest PDF/URL/DJVU/media into corpus |
| Ingest | `shutong_ingest_status` | check ingestion progress |
| Ingest | `shutong_delete_document` | remove document from corpus |
| Paper | `shutong_paper_use`, `shutong_paper_status`, `shutong_paper_audit`, `shutong_paper_export_docx` | activation, gates, status, and export |
| Workspace | `shutong_workspace` | `create_paper`, `create_project`, `create_work`, `list`, `plan_switch`, `activate` |
| Paper evidence | `shutong_bibliography`, `shutong_source`, `shutong_note`, `shutong_claim` | approval, lawful access, notes, and claims |
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
├── opencode.json                # OpenCode MCP + agent config
├── .mcp.json                    # Claude Code MCP config
├── .claude/                     # Claude Code agents + skills
├── .codex/                      # Codex config + agents + skills
├── .opencode/                   # OpenCode specialist agents
├── .shutong/                    # local paper data, glossary, and compatibility artifacts
├── adapters/                    # DeepSeek Harness plugin + adapter README
├── packages/shutong-backend/    # Python backend (the agent)
│   ├── shutong_backend/
│   │   ├── mcp_server.py        # MCP tool surface (40 tools)
│   │   ├── rpc_server.py        # NDJSON RPC surface
│   │   ├── agents/              # pipeline, chat, writing, review, memory
│   │   ├── state.py             # unified research state facade
│   │   └── tools/               # research, ingest, verify, translate, corpus, code
│   └── tests/
├── shutong/                     # Bun launcher (scaffolding CLI)
├── scripts/                     # standalone ingest/export/search helpers
├── corpus/                      # digitalized, indexed source derivatives
├── library/                     # preserved original source files
└── papers/                      # paper manifests, drafts, and notes
```

---

## Key Design Rules

- **No embeddings.** All retrieval is BM25 keyword search — deterministic and reproducible.
- **Merkle-verified.** Every text node has a SHA-256 hash. Document integrity is a Merkle tree.
- **Fail-closed integrity.** The integrity verifier rejects answers where any hash, Merkle proof, or citation key fails.
- **Host-side translation.** Preserve citations and established domain terminology; translation is not an MCP workflow.
- **Backend-as-agent.** The Python backend owns the pipeline, state, and enforcement; hosts are thin adapters.
- **Structured errors.** Every tool error returns `{status: "error", error_code, message, next_action}`.
- **Scholar-first.** The default agent mode is a research assistant, not a generic coding shell.

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
