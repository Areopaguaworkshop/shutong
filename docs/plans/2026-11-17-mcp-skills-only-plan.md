# MCP and Skills Only

Supersedes `2026-11-17-agent-design-parity-plan.md`. That plan added per-role agent
configuration; this one removes the agent layer instead.

## Goal

Ship Shutong as two portable surfaces — one MCP server and one skill pack — so any
OpenCode-like host can use it without per-role agent definitions, per-role model
config, or host-specific agent files.

The backend stays "the agent" in the sense `adapters/README.md:4-6` already claims:
it owns the pipeline, state, and integrity. The host keeps its own agent runtime.

## Why this is coherent

- The MCP server already carries the behaviour: 26 tools, fail-closed evidence gates
  in Python (`papers.py:292-325`, `:377-454`, `:537-566`).
- Skills are portable across hosts by convention: `.agents/skills`,
  `.claude/skills`, `.codex/skills`, `.pi/skills`.
- Agent definitions are not portable: three formats, three key sets, and no shared
  semantics for model, tools, or delegation.
- The role prompts are the only content that agents actually add. They can live in
  `SKILL.md` files, which every host reads.

## What is removed

| Target | Path | Count |
| --- | --- | --- |
| OpenCode agents | `.opencode/agents/*.md` | 6 |
| Claude Code agents | `.claude/agents/*.md` | 10, including legacy roles |
| Codex agents | `.codex/agents/*.toml` | 10, including legacy roles |
| Agent rendering | `shutong/src/cli/renderer.ts` agent branches and template maps | 5 maps |
| Agent parity plan | `docs/plans/2026-11-17-agent-design-parity-plan.md` | marked superseded |

## Where the role prompts go

The project skills are one-liners today, for example `.agents/skills/noter/SKILL.md`
carries a single sentence. The full role prompts live only in the agent files. The
migration moves each prompt into the skill that owns that work.

| Former role | Skill that absorbs it | Skills it composes |
| --- | --- | --- |
| Conductor | `AGENTS.md` routing section, no skill | all |
| Bibliographer | `explore-bibliography` | `copyright-access` |
| Ingestor | `ingest-source` | `copyright-access` |
| Noter | `noter` | `text-analysis`, `evidence-synthesis`, `translate-academic` |
| Verifier | `verify-bibliography` | `verify-corpus`, `citation-check` |
| Workspace Planner | `workspace-planner` | `paper-workspace` |

Each rewritten `SKILL.md` carries four sections, in this order:

1. **Role** — the paragraph now in the agent file.
2. **Tools** — the MCP tool names this role may call.
3. **Evidence gate** — what must exist before this role may act, with file:line from
   the backend.
4. **Never** — the prohibitions already listed in the architecture doc.

## Config after the change

`.shutong/config.toml` keeps paths and the backend LLM only. No `preset`, no
`agents` table, no per-role model.

```toml
[project]
corpus_root = "corpus"
library_root = "library"

[backend]
python = "packages/shutong-backend/.venv/bin/python"
module = "shutong_backend.mcp_server"

[model]
provider = "ollama"
name = "deepseek-v4-pro:cloud"
```

Model choice becomes a host concern: one session model, chosen by the user in the
host, applies to every skill the session loads.

## Host matrix

| Host | MCP entry | Skills root | Instructions |
| --- | --- | --- | --- |
| OpenCode | `opencode.json` `mcp.shutong` | `.agents/skills` | `AGENTS.md` |
| Claude Code | `.mcp.json` `mcpServers.shutong` | `.agents/skills` and `.claude/skills` | `CLAUDE.md` imports `AGENTS.md` |
| Codex | `.codex/config.toml` `[mcp_servers.shutong]` | `.codex/skills` | `AGENTS.md` |
| Pi | `.pi/mcp.json` | `.pi/skills` and `.agents/skills` | `AGENTS.md` |
| Hermes | user-managed config | `.agents/skills` | `AGENTS.md` |

`renderHostArtifacts` keeps only three jobs: write skills into the host's root, merge
the MCP entry, and write or update the instructions file.

## What this costs

| Loss | Effect | Mitigation |
| --- | --- | --- |
| Per-role models | One model for the whole session | The user changes the session model per host |
| Isolated Verifier context | The Verifier reads the same context as the author | `verify-bibliography` requires fresh evidence and a recorded `sha256`; the backend still refuses unverified claims (`papers.py:421-438`) |
| Per-role tool sandboxing | Any skill can call any MCP tool | Gates live in the backend, not in the tool list; every write path validates its preconditions |
| Delegation allowlists | No declared subagent topology | `AGENTS.md` states the routing rule; hosts that support subagents may still use them |

The last two are the real trade-off: independence becomes procedural, not structural.
Record it in `docs/archetecture-2026-08-29.md` so nobody claims the Verifier is
isolated when it is not.

## Work plan

### Phase 0 — safety

The project is not a git repository. Copy `.opencode/agents`, `.claude/agents`,
`.codex/agents`, and `shutong/src/cli/renderer.ts` to
`~/.local/share/shutong/backups/2026-11-17-agents/` before any deletion.
Validation: the copy lists 26 files and `diff -r` reports no differences.

### Phase 1 — rewrite skills

1. Merge each role prompt into its skill, with the four sections above.
2. Keep every existing skill name; add nothing that duplicates one.
3. Validation: each rewritten `SKILL.md` names its tools; a grep shows no skill
   referencing a removed agent file or `shutong_pipeline`.

### Phase 2 — strip agent rendering

1. Delete the agent branches, `renderMarkdownAgent`, `specialistAgents`,
   `shutongConductor`, `codexAgentTemplates`, and `analysisRoleGuidance` from
   `renderer.ts`.
2. Keep `renderHostArtifacts` for skills, MCP entry, and instructions only.
3. Validation: `shutong init --dry-run` lists no `agents/` paths; `tsc --noEmit`
   passes; `bun test` if the package has tests.

### Phase 3 — remove generated agent files

1. Delete the three agent directories and the legacy `.shutong/agents/` copies that
   `templates.py:67-73` writes.
2. Update `templates.py` so `init` no longer writes `.shutong/agents`.
3. Validation: a fresh `shutong init` in a temp directory creates skills, MCP config,
   and `AGENTS.md`, and no agent files.

### Phase 4 — doctor and docs

1. `doctor --agents` becomes `doctor --surface`: assert the MCP server answers 26
   tools, the skill pack exists in the host root, and `AGENTS.md` carries the routing
   section.
2. Update `docs/archetecture-2026-08-29.md`, `adapters/README.md`, `README.md`, and
   `.mcp.json` comments to describe MCP plus skills only.
3. Validation: `doctor --surface` passes on this machine; the docs contain no agent
   path references.

## Execution record — 2026-11-17

All four phases ran on this machine. Evidence:

| Phase | Result | Proof |
| --- | --- | --- |
| 0 backup | 38 files copied | `diff -r` clean against all three agent dirs and `renderer.ts` |
| 1 skills | 5 role skills rewritten; 12 others untouched | `grep -c '^## '` = 4 in each; checksums identical for the other 12 |
| 1 cleanup | 3 stale skills fixed | `academic-pipeline`, `translate-academic`, `verify-corpus`; no removed-tool names remain |
| 2 renderer | agent layer deleted; 4 jobs kept | `bun run typecheck` exit 0; projection emits 46 files, 0 agent paths |
| 3 files | 3 agent dirs + `.shutong/agents` + `templates/agents` removed | fresh `initProject` writes 25 files, 0 agent paths |
| 3 tests | agent assertions inverted | `bun test` 29 pass, 0 fail |
| 4 doctor | `doctor --surface` added | 26 tools, role skills present, no agent layer, routing found |
| 4 docs | README, adapters README, architecture doc, AGENTS.md, init template | no removed-tool names on any live surface |

Tooling added during execution: `bun@1.3.13` (project pin) and `bun install` at the
workspace root, because the workspace had no `node_modules`.

Follow-up worth a ticket: the running host keeps the deleted subagents in its agent
list until it reloads. Reload OpenCode to see the reduced surface.

## Acceptance

- `grep -r "agents/" --include=*.ts --include=*.py` returns only unrelated matches.
- A fresh project gets MCP, skills, and `AGENTS.md`, nothing else.
- Every specialist behaviour is reachable through a skill by name.
- No document claims per-role models or an isolated Verifier.

## Findings during execution

- `shutong_workspace` `plan_switch` and `activate` require a `confirmed` flag that
  the published group schema never declares (`mcp_server.py` `_GROUP_PROPERTIES`).
  The skill documents the real requirement; the schema should expose it. Backlog.
- `ingest-source/SKILL.md` ships no `name` key in its frontmatter. Left as found;
  add one only if a loader requires it.
- The workspace had no installed dependencies and no `bun`. Validation uses
  `bun@1.3.13` (project pin in root `package.json`) and `bun install` at the
  workspace root; `bun run typecheck` was clean before Phase 2.
- Three skills outside Phase 1 scope still named removed tools
  (`academic-pipeline` → `shutong_pipeline`, `translate-academic` →
  `shutong_glossary_lookup`, `verify-corpus` → `shutong_verify_all`). All three were
  rewritten or corrected during Phase 1 verification.
