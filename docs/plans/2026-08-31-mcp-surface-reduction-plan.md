# MCP Surface Reduction Plan

## Goal

Keep one Shutong MCP server while reducing its public tool menu from 66 tools to
25 workflow-focused tools. Removed names are neither advertised nor callable
by Codex, Claude Code, or OpenCode.

## Scope Decision

The architecture is Shutong conductor plus Bibliographer, Ingestor, Noter,
Verifier, and Workspace Planner. Translation, glossary management, and the
legacy Translator role are outside that team and will be removed rather than
hidden behind new wrappers.

Remove these public tools and their related skills, commands, templates, and
agent prompts:

- `shutong_translate`, `shutong_translate_url`, `shutong_render_bilingual`
- `shutong_glossary_lookup`, `shutong_glossary_add`, `shutong_glossary_list`,
  `shutong_glossary_load`
- `translate-zh` skill, glossary command, glossary templates, Translator role

Translation remains an explicit host-agent task governed by `AGENTS.md`; it is
not a Shutong backend workflow.

## Target Public Surface

Keep these direct tools:

1. `shutong_status`
2. `shutong_state_wake_up`
3. `shutong_state_snapshot`
4. `shutong_state_record_session`
5. `shutong_bibliography_search`
6. `shutong_bibliography_source_catalog`
7. `shutong_ingest`
8. `shutong_ingest_status`
9. `shutong_delete_document`
10. `shutong_search`
11. `shutong_verify`
12. `shutong_paper_audit`
13. `shutong_paper_export_docx`
14. `shutong_paper_status`
15. `shutong_paper_use`

Replace low-level tool families with these grouped tools:

| Grouped tool | Actions absorbed |
|---|---|
| `shutong_workspace` | create standalone paper, create project, create work, list, plan switch, activate |
| `shutong_bibliography` | set, update, import, approve |
| `shutong_source` | classify access, authorize, add, mark ingested |
| `shutong_note` | add, search, verify |
| `shutong_claim` | add, verify |
| `shutong_corpus` | status, tree |
| `shutong_search` | keyword and regex modes |
| `shutong_verify` | node and whole-corpus modes |
| `shutong_citation` | resolve, render, tree |
| `shutong_memory` | search, list, save |
| `shutong_outreach` | record public contact, draft unsent outreach |
| `shutong_verifier_report` | record or scholar-override report |

The resulting public surface is 25 tools. Each grouped tool has a closed
`action` enum and action-specific required fields; it must not accept an
unstructured catch-all payload.

## Tools Removed from the Public Menu

- Legacy `shutong_chat` and `shutong_pipeline`, which bypass paper-scoped
  evidence gates.
- `shutong_file_read`, `shutong_file_write`, `shutong_file_edit`,
  `shutong_file_list`, `shutong_bash`, `shutong_grep`, and `shutong_glob`.
- All individual low-level tools replaced by the grouped tools above.
- Translation and glossary tools listed in Scope Decision.

## Implementation Steps

1. Define the grouped tool schemas and dispatchers in `mcp_server.py`.
2. Update the bundled Bun RPC registry, conductor/specialist prompts, Codex
   skills, Claude agents, and OpenCode agents to use grouped tools only.
3. Remove Translator, translation skills, glossary skills, commands, and
   templates from all generated host artifacts.
4. Delete legacy handler mappings and old tool definitions. Calls to removed
   names must return `unknown_tool`; no compatibility aliases are retained.
5. Update README architecture, workflow, and MCP tool count.
6. Add tests for every action schema, rejected legacy calls, paper gates, and
   identical generated public tool configuration across hosts.

## Acceptance Criteria

- Exactly one MCP server is registered per host.
- `list_tools` exposes exactly 25 Shutong tools.
- The approved bibliography → ingested source → verified note → claim → draft
  gate remains enforced.
- No generated agent, skill, command, CLI registry, or README instruction
  references a removed legacy tool.
- Removed legacy MCP calls return `unknown_tool`.
- Codex, Claude Code, and OpenCode generate the same public tool contract.

## Implementation Status — 2026-08-31

- Completed: public MCP discovery, dispatch, and the bundled Bun registry expose
  exactly 25 names; removed calls return `unknown_tool`.
- Completed: grouped actions have closed enums plus action-specific required
  fields, including standalone paper creation through `shutong_workspace`.
- Completed: `shutong_search` supports keyword/regex modes and
  `shutong_verify` supports node/whole-corpus modes.
- Completed: generated Codex, Claude Code, and OpenCode artifacts use the
  grouped contract; translation/glossary artifacts are removed and host-side
  translation guidance remains in `AGENTS.md`.
