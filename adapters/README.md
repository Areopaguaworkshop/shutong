# Shutong Host Adapters

Shutong is a host-agnostic academic-research application. The Python backend
(`packages/shutong-backend`) is the agent — it owns the pipeline, state, and
integrity. Each host below is a thin adapter that registers the MCP server and
receives the skill pack. Shutong ships no agent definitions; role behaviour lives
in the skills, and routing lives in `AGENTS.md`.

## Architecture

```
Host primary agent (OpenCode / Claude Code / Codex / Pi / DeepSeek Harness)
        │  MCP (or NDJSON RPC for DeepSeek Harness)
        ▼
Python backend = THE AGENT
  ├── workflow tools     — research, bibliography, ingest, note, claim, audit
  ├── shutong_state_*    — cross-session state (wake_up / snapshot / record_session)
  ├── shutong_status     — corpus + integrity + state visibility
  └── domain tools       — search / verify / ingest / citation / analysis
```

## Adapters

| Host | MCP registration | Agent definitions | Skills | Session instructions |
|------|------------------|--------|--------|-------------------------|
| **OpenCode** | `opencode.json` `mcp.servers.shutong` | none | `.agents/skills/*/SKILL.md` | `AGENTS.md` |
| **Claude Code** | `.mcp.json` | none | `.claude/skills/*/SKILL.md` | `CLAUDE.md` |
| **Codex** | `.codex/config.toml` `[mcp_servers.shutong]` | none | `.codex/skills/*/SKILL.md` | `AGENTS.md` (auto-load) |
| **Pi** | `.pi/mcp.json` `mcpServers.shutong` | none | `.pi/skills/*/SKILL.md` | host instructions |
| **DeepSeek Harness** | `adapters/deepseek-harness/shutong.ts` (NDJSON RPC bridge) | none | plugin `ctx.systemPrompt` | plugin `agent.inject()` |

## Session-start wake-up

Every host injects cross-session context at session start via `shutong_state_wake_up`:

- **OpenCode / Codex**: `AGENTS.md` instructs the agent to call `shutong_state_wake_up` first.
- **Claude Code**: `CLAUDE.md` does the same.
- **DeepSeek Harness**: the plugin calls `state_wake_up` and injects it via `agent.inject()` automatically.

## Manual MCP configurations

- **OMP (oh-my-pi)** uses its own `mcpServers` config; see `docs/publishing.md`.
- **Hermes** receives a generated setup note. Add the MCP entry to Hermes' own
  configuration; Shutong does not edit global user config.

## DeepSeek Harness caveat

`deepseek-ai/deepseek-harness` is developer preview with breaking changes. The
adapter targets the Cordis plugin API as documented; verify against the installed
`@deepseek-ai/cordis` version before relying on it.
