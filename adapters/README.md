# Shutong Host Adapters

Shutong is a host-agnostic academic-research application. The Python backend
(`packages/shutong-backend`) is the agent — it owns the pipeline, state, and
integrity. Each host below is a thin adapter that registers the MCP server and
receives the skill pack. Shutong ships no agent definitions; role behaviour lives
in the skills, and routing lives in `AGENTS.md`.

## Architecture

```
Host (OpenCode / Claude Code / Codex / DeepSeek Harness)
        │  MCP (or NDJSON RPC for DeepSeek Harness)
        ▼
Python backend = THE AGENT
  ├── workflow tools     — research, bibliography, ingest, note, claim, audit
  ├── shutong_state_*    — cross-session state (wake_up / snapshot / record_session)
  ├── shutong_status     — corpus + integrity + state visibility
  └── domain tools       — search / verify / ingest / citation / analysis
```

## Adapters

| Host | MCP registration | Agents | Skills | Session-start injection |
|------|------------------|--------|--------|-------------------------|
| **OpenCode** | `opencode.json` `mcp.shutong` | none | `.agents/skills/*/SKILL.md` | `AGENTS.md` (auto-load) |
| **Claude Code** | `.mcp.json` | none | `.agents/skills`, `.claude/commands` | `CLAUDE.md` (auto-load) |
| **Codex** | `.codex/config.toml` `[mcp_servers.shutong]` | none | `.codex/skills/*/SKILL.md` | `AGENTS.md` (auto-load) |
| **DeepSeek Harness** | `adapters/deepseek-harness/shutong.ts` (NDJSON RPC bridge) | none | plugin `ctx.systemPrompt` | plugin `agent.inject()` |

## Session-start wake-up

Every host injects cross-session context at session start via `shutong_state_wake_up`:

- **OpenCode / Codex**: `AGENTS.md` instructs the agent to call `shutong_state_wake_up` first.
- **Claude Code**: `CLAUDE.md` does the same.
- **DeepSeek Harness**: the plugin calls `state_wake_up` and injects it via `agent.inject()` automatically.

## Not yet adapted

- **Hermes** — no verifiable coding-agent CLI named "Hermes" exists in the 2026
  ecosystem. If you mean a specific product, provide a repo/URL and I'll add its adapter.
- **Pi** — ambiguous; Inflection's Pi is a chatbot, not an agent CLI with MCP config.
  Same: provide a repo/URL to confirm the target.

## DeepSeek Harness caveat

`deepseek-ai/deepseek-harness` is developer preview with breaking changes. The
adapter targets the Cordis plugin API as documented; verify against the installed
`@deepseek-ai/cordis` version before relying on it.
