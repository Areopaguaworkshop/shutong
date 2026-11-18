# Agent Design Parity with oh-my-opencode-slim

> **Superseded 2026-11-17.** The scholar chose an MCP plus skills surface with no
> agent layer. See `2026-11-17-mcp-skills-only-plan.md`. Keep this document only as
> a record of the capability analysis.

## Goal

Give Shutong the agent-design system oh-my-opencode-slim has, without adopting its
plugin runtime: per-role model, variant, temperature, step budget, skill grants,
MCP tool scope, delegation allowlist, and prompt overrides — expressed in one
versioned config, projected into every supported host.

Scope is the six Shutong roles only. The evidence lineage stays backend-enforced;
this plan changes how roles are configured and projected, not who may draft.

## What parity means

| Capability | oh-my-opencode-slim | Shutong target | Host support |
| --- | --- | --- | --- |
| Per-agent model | `model` string or ordered fallback array | `model` string, preset-scoped | opencode, claude, codex |
| Reasoning variant | `variant` passed to the host | `variant` passed through | opencode |
| Temperature | `temperature` in request settings | `temperature` | opencode, claude |
| Step budget | not exposed | `steps` (opencode `AgentConfig.steps`) | opencode |
| Skill grants | `skills` with `*` and `!name` | same grammar → `permission.skill` map | opencode (native) |
| MCP tool scope | `mcps` with `*` and `!name` → `<ns>_*` permissions | same, scoped to `shutong_*` | opencode (native) |
| Delegation control | `permission.task` stances, no nested dispatch | `permission.task` stances | opencode |
| Prompt override | `prompt` config, then `<dir>/<agent>.md`, then builtin | file-first with append file | all |
| Presets | `presets` with `extends` | `presets` with `extends` | all |
| In-memory registration | JS `config` hook | generated files plus host config | n/a |

Non-goals, because they need the JS plugin ABI: runtime model fallback chains,
background job pools, TUI state, auto-update hooks, council agents.

## Decisions

D1. **One config surface.** Extend the existing config files, do not add a new file
type. `.shutong/config.toml` gains `[presets.<name>.agents.<role>]`; the user file
`~/.config/shutong/config.toml` may override any role. `src/engine/config.ts`
already loads and merges both (`resolveConfigPaths`).

D2. **One prompt source.** Move the role prompts out of the three TypeScript string
maps (`renderer.ts:1-66`, `:47-63`, `:110-140`) into
`packages/shutong-backend/shutong_backend/templates/agents/<role>.md`. That
directory already exists with `bibliographer.md`, `ingestor.md`, `noter.md`,
`verifier.md`, `workspace-planner.md`. Renderer reads it once per role.

D3. **Capability-aware projection.** Each host gets only the keys it supports, and
unsupported capabilities are reported, not silently dropped. Claude has model
aliases and a tool allowlist; Codex has model, reasoning effort, and sandbox mode;
opencode gets the full key set.

D4. **No pinned models in shipped templates.** Delete `model = "gpt-5.6"` from the
four Codex templates (`renderer.ts:110-140`), which contradicts the portability note
in the Noter template and fails on this machine.

D5. **Draft authority is not configurable.** Every role is tunable, but only the
conductor may author prose, and only through the existing gates
(`papers.py:446-453`, `:537-566`). A preset cannot grant drafting to a specialist.

D6. **Skill grants are enforced, not advisory.** Compile them into
`permission.skill` maps, the same mechanism oh-my-opencode-slim uses
(`getSkillPermissionsForAgent`, dist `index-01tcrt5t.js:1978-2005`). Do not rely on
prompt text alone.

D7. **Recursion guard.** The conductor gets `permission.task` with the five
specialists allowed and `"*": "deny"`. Every specialist gets `{"*": "deny"}`, so no
nested dispatch.

D8. **Config resolution order.** project preset, then user preset, then per-role
`agents.<role>` override, then CLI flag. First value wins per key, not per object.

## Config shape

```toml
# .shutong/config.toml
preset = "local-ollama"

[presets.local-ollama.agents.shutong]
model = "ollama/deepseek-v4-pro:cloud"
variant = "high"
steps = 40
skills = ["*"]
mcps = ["shutong"]

[presets.local-ollama.agents.shutong-verifier]
model = "ollama/qwen3.5:cloud"
variant = "high"
temperature = 0.1
skills = ["verify-corpus", "verify-bibliography", "citation-check"]
mcps = ["!*", "shutong_verify", "shutong_verifier_report", "shutong_citation", "shutong_analysis"]

[presets.local-ollama.agents.shutong-ingestor]
model = "ollama/glm-5.3-flash:cloud"
temperature = 0.0
skills = ["ingest-source", "copyright-access"]
mcps = ["!*", "shutong_ingest", "shutong_ingest_status", "shutong_source"]

[presets.cloud-split]
extends = "local-ollama"

[user.agents.shutong-noter]
model = "anthropic/claude-opus-4"
```

Key grammar matches oh-my-opencode-slim: `*` grants all, `!name` revokes, and
revocation beats grant. `mcps` accepts either server names (`shutong`) or explicit
tool names (`shutong_verify`), so one grammar covers both scopes.

## Generation pipeline

```
.shutong/config.toml + ~/.config/shutong/config.toml
        │  resolveAgentConfig()  (new, src/engine/agents.ts)
        ▼
ResolvedRole[6] {model, variant, temperature, steps, skills, mcps, task, promptFile}
        │
        ├─ opencode: .opencode/agents/<role>.md  frontmatter + prompt
        │            fallback: opencode.json "agent" block when a key is rejected
        ├─ claude:   .claude/agents/<role>.md    model alias + tools allowlist
        ├─ codex:    .codex/agents/<role>.toml   model + reasoning effort + sandbox
        └─ doctor:   .shutong/agent-resolution.json  (resolved view, for audit)
```

Opencode frontmatter target:

```markdown
---
description: Paper-scoped note specialist. ...
mode: subagent
model: ollama/deepseek-v4-pro:cloud
variant: high
temperature: 0.2
steps: 40
permission:
  skill:
    "*": deny
    text-analysis: allow
    evidence-synthesis: allow
  task:
    "*": deny
  shutong_*: deny
  shutong_note: allow
  shutong_claim: allow
  shutong_analysis: allow
  shutong_search: allow
---
```

`variant`, `steps`, and `permission` are valid `AgentConfig` keys
(`https://opencode.ai/config.json` `$defs.AgentConfig`). If a markdown frontmatter
key is rejected at load, the generator moves that role's keys into the
`opencode.json` `agent` block, which accepts the same object.

## Work plan

### Phase 1 — prompt single-source (no behaviour change)

1. Add `templates/agents/shutong.md` for the conductor; keep the five existing files.
2. Rewrite `renderer.ts` to load prompts from that directory for all three hosts.
3. Delete `specialistAgents`, `shutongConductor`, and `codexAgentTemplates` string
   bodies; keep only the file paths.
4. Validation: `diff` generated `.opencode/agents/*.md` before and after; only the
   Codex `model` lines may change. `shutong init --dry-run` lists identical paths.

### Phase 2 — resolved config

1. Add `ResolvedRole` to `src/shared/types.ts`.
2. New `src/engine/agents.ts`: read `presets`, apply `extends`, merge user overrides,
   expand `*`/`!name`, return six resolved roles plus a per-key provenance map.
3. Emit `.shutong/agent-resolution.json` so the auditor can see which layer set what.
4. Validation: unit tests for precedence, `!name` revocation, `extends`, and a
   missing-model case. No host files touched in this phase.

### Phase 3 — opencode projection

1. Render `model`, `variant`, `temperature`, `steps`, `permission.skill`,
   `permission.task`, and per-tool `shutong_*` permissions into each role file.
2. Conductor: `permission.task` allows the five specialists, denies `*`.
3. Specialists: `permission.task` is `{"*": "deny"}`.
4. Validation: `opencode` loads with no config warnings; `/agents` shows six roles;
   a denied tool call returns a permission error, not a tool result. Capture both.

### Phase 4 — claude and codex projection

1. Claude: emit `model` alias only when the preset names one; emit `tools` as an
   explicit allowlist derived from `mcps`. Report `variant`, `steps`, `permission.skill`
   as unsupported for this host in the resolution file.
2. Codex: emit `model` only when pinned, `model_reasoning_effort` from `variant`,
   `sandbox_mode` fixed at `read-only` for specialists.
3. Validation: `claude` and `codex` start without config errors; the resolution file
   lists the same six roles with host-specific gaps marked.

### Phase 5 — doctor and smoke tests

1. `shutong-backend doctor --agents` asserts: six roles resolved; every `model`
   either resolves in the provider list or is explicitly `inherit`; every skill and
   tool name in a grant exists; no specialist has task dispatch; no template carries
   a hardcoded model.
2. Smoke test per role: call one allowed tool and one denied tool; assert allow
   returns data and deny returns a permission error.
3. Add the result to `shutong_status` output so the host can see agent health.

## Risks

- **Frontmatter limits.** If opencode ignores `permission` in markdown agents, the
  fallback is the `opencode.json` `agent` block. Phase 3 verifies this before Phase 4.
- **Three projections drift.** The resolution file is the single audit surface; the
  doctor check compares it against generated files.
- **Model churn.** Presets name cloud models that rotate. Keep `local-ollama` as the
  default and never ship pinned models in templates.
- **User overrides vs init.** `writeIfMissing` (`renderer.ts:73-77`) already protects
  edited files. Phase 3 must keep that behaviour and add `--force` only on request.

## Files touched

- `shutong/src/cli/renderer.ts` — projection, prompt loading
- `shutong/src/engine/agents.ts` — new resolver
- `shutong/src/engine/config.ts` — read `preset` and `presets`
- `shutong/src/shared/types.ts` — `ResolvedRole`, preset types
- `shutong/src/cli/init.ts` — write resolution file, extend `--dry-run`
- `packages/shutong-backend/shutong_backend/templates/agents/*.md` — prompt source
- `packages/shutong-backend/shutong_backend/doctor.py` — `--agents` checks
- `docs/` — this plan plus the capability matrix above
