# Publishing Shutong as an MCP server — first release 0.0.1

Verified against this machine (2026-11-17) and current 2026 docs. Publish in this
order; each step is a gate for the next.

## What gets published

| Artifact | Registry | Identifier | Status |
| --- | --- | --- | --- |
| Python backend + MCP server | PyPI | `shutong-backend` | name free (404) |
| Registry metadata | MCP Registry | `io.github.<user>/shutong` | needs GitHub auth |
| Optional TS CLI wrapper | npm | `shutong-backend-mcp` | name free, not required |

The MCP server is Python, so PyPI plus `uvx` is the primary route. npm is optional.

## Blockers to clear first

1. **No LICENSE file.** PyPI and the registry both expect one. The ecosystem is MIT
   (citeindex, the MCP SDK). Add `LICENSE` at the repo root and `license = "MIT"`.
2. **Package README.** PyPI greps the long description for the ownership marker
   `mcp-name: io.github.<user>/shutong`. Without it the registry publish is rejected.
   Add `packages/shutong-backend/README.md` with that line and `readme = "README.md"`.
3. **Heavy prerequisite.** Shutong depends on `citeindex==0.13.2`, a separate upstream
   project on PyPI. It pulls paddlepaddle, mineru, whisperx, pyannote and playwright,
   so the first install is ~13 GB. This is a documented prerequisite, not something
   Shutong vendors or forks. Users install it transitively through `uvx` or directly
   in their own environment.
4. **Version conflict.** Local is `0.4.0`. PyPI numbers are immutable, so publishing
   `0.0.1` burns that number for the workspace build forever. If 0.4.0 is only
   internal, reset everything to `0.0.1` now.
5. **Credentials.** None exist here: no `~/.pypirc`, `npm whoami` is unauthenticated,
   `gh` is logged out.

## Step 0 — metadata and version

```bash
cd /path/to/shutong
# 1. LICENSE (MIT), 2. packages/shutong-backend/README.md with:
#    mcp-name: io.github.<gh-user>/shutong
```

`packages/shutong-backend/pyproject.toml`:

```toml
[project]
name = "shutong-backend"
version = "0.0.1"
description = "Citation-verified scholarly research over a local corpus (MCP server)"
readme = "README.md"
license = "MIT"
requires-python = ">=3.12"
```

Keep the three scripts as they are, especially:

```toml
[project.scripts]
shutong-backend-mcp = "shutong_backend.mcp_server:main"
```

## Step 1 — declare citeindex as a prerequisite

`citeindex` is a separate project with its own release cycle. Shutong consumes it
and must not vendor, fork, or copy its modules. Keep it in `dependencies`:

```toml
dependencies = [
  "citeindex==0.13.2",
  "mcp>=1.27,<2",
  "click>=8.0", "pyyaml>=6.0", "jsonschema>=4.20",
  "requests>=2.31", "python-dateutil>=2.8", "lxml>=4.9",
]
```

What the user needs to know, and what the package README and `doctor` must state:

- First install is large: citeindex brings paddlepaddle, mineru, whisperx, pyannote
  and playwright, roughly 13 GB of wheels.
- A network connection is required during the first `uvx` run.
- Ingestion needs the full set; searching, verifying, notes and audits still import
  citeindex, so there is no reduced subset in this release.

Do not pin `mcp>=2.3` yet: this code imports `mcp.server.Server` and runs on
1.27.0. Pin what you tested, then test 2.x deliberately.

## Step 2 — build and test the artifact locally

```bash
cd packages/shutong-backend
rm -rf dist
uv build --no-sources          # --no-sources is required: the repo root declares a path source
ls dist/                        # wheel + sdist
uvx --from ./dist/shutong_backend-0.0.1-py3-none-any.whl shutong-backend-mcp < /dev/null
```

The wheel already carries the skill templates: verified 17 template files and 9
skills, zero agent templates. Stdout must stay clean — any banner corrupts JSON-RPC.

## Step 3 — publish to PyPI

```bash
cd packages/shutong-backend
UV_PUBLISH_TOKEN=pypi-... uv publish
```

Then prove the public install works before touching the registry:

```bash
uvx shutong-backend-mcp < /dev/null
uvx --from 'shutong-backend==0.0.1' shutong-backend-mcp < /dev/null
```

## Step 4 — registry entry

```bash
# install the publisher (v1.8.9)
curl -L https://github.com/modelcontextprotocol/registry/releases/download/v1.8.9/mcp-publisher_linux_amd64.tar.gz \
  | tar xz -C /tmp/opencode mcp-publisher && install -Dm755 /tmp/opencode/mcp-publisher ~/.local/bin/mcp-publisher

cd packages/shutong-backend
mcp-publisher init
mcp-publisher validate
mcp-publisher login github --token "$GH_PAT"   # org namespaces need a PAT, not the device flow
mcp-publisher publish
```

`server.json` for 0.0.1:

```json
{
  "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
  "name": "io.github.<gh-user>/shutong",
  "title": "Shutong",
  "description": "Citation-verified scholarly research over a local corpus",
  "repository": { "url": "https://github.com/<gh-user>/shutong", "source": "github" },
  "version": "0.0.1",
  "packages": [{
    "registryType": "pypi",
    "identifier": "shutong-backend",
    "version": "0.0.1",
    "runtimeHint": "uvx",
    "transport": { "type": "stdio" },
    "environmentVariables": [
      { "name": "SHUTONG_CORPUS_ROOT", "description": "Absolute corpus path", "isRequired": false }
    ]
  }]
}
```

Rules that reject a publish: description over 100 characters, a range as version,
`"version": "latest"`, package not yet public, missing `mcp-name:` marker, or a
registry host other than `pypi.org` / `registry.npmjs.org`.

## Step 5 — what users paste

Claude Desktop, `claude_desktop_config.json`:

```json
{ "mcpServers": { "shutong": { "command": "uvx", "args": ["shutong-backend-mcp"],
  "env": { "SHUTONG_CORPUS_ROOT": "/abs/path/to/corpus" } } } }
```

Claude Code:

```bash
claude mcp add --transport stdio --scope user shutong -- uvx shutong-backend-mcp
```

Codex, `~/.codex/config.toml`:

```toml
[mcp_servers.shutong]
command = "uvx"
args = ["shutong-backend-mcp"]
env = { SHUTONG_CORPUS_ROOT = "/abs/path/to/corpus" }
```

OpenCode V2, `opencode.json` — note the nested `mcp.servers`:

```json
{ "mcp": { "servers": { "shutong": { "type": "local",
  "command": ["uvx", "shutong-backend-mcp"],
  "environment": { "SHUTONG_CORPUS_ROOT": "/abs/path/to/corpus" } } } } }
```

Cursor, `~/.cursor/mcp.json`: same `mcpServers` shape as Claude Desktop.

Pi, `~/.pi/agent/mcp.json` (project: `.pi/mcp.json`, read after project trust):

```json
{ "mcpServers": { "shutong": { "command": "uvx", "args": ["shutong-backend-mcp"],
  "env": { "SHUTONG_CORPUS_ROOT": "/abs/path/to/corpus" } } } }
```

```bash
pi mcp add shutong --env SHUTONG_CORPUS_ROOT=/abs/path/to/corpus -- uvx shutong-backend-mcp
```

OMP (oh-my-pi), `~/.omp/agent/mcp.json` (project: `.omp/mcp.json`):

```json
{ "$schema": "https://raw.githubusercontent.com/can1357/oh-my-pi/main/packages/coding-agent/src/config/mcp-schema.json",
  "mcpServers": { "shutong": { "type": "stdio", "command": "uvx", "args": ["shutong-backend-mcp"],
  "env": { "SHUTONG_CORPUS_ROOT": "${SHUTONG_CORPUS_ROOT:-/abs/path/to/corpus}" } } } }
```

OMP has no `omp mcp` subcommand; use the in-TUI `/mcp add`, then `/mcp reload`, `/mcp list`,
`/mcp test shutong`. Both hosts run stdio servers launched through `uvx`.

## Step 6 — npm wrapper (optional)

Only needed if you want `npx -y shutong-backend-mcp` to work. The wrapper shells out
to `uvx`; it does not reimplement the server.

```json
{ "name": "shutong-backend-mcp", "version": "0.0.1", "type": "module",
  "mcpName": "io.github.<gh-user>/shutong",
  "bin": { "shutong-backend-mcp": "dist/cli.js" }, "files": ["dist"], "engines": { "node": ">=20" } }
```

`npm publish --access public`, then confirm `npx -y shutong-backend-mcp@0.0.1`.

## Version discipline

Keep `server.json.version` == `packages[].version` == `pyproject.toml.version` == git
tag `v0.0.1`. PyPI and npm files are immutable per version, and registry entries are
immutable per version string, so every metadata fix costs a new number.

## Published state — 2026-11-18

| Item | State | Evidence |
| --- | --- | --- |
| PyPI `shutong-backend==0.0.2` | published | `uv tool install shutong-backend==0.0.2` → `shutong 0.0.2`, 26 tools |
| PyPI `0.0.1` | published, broken console script | `shutong-backend-mcp` exited with `coroutine never awaited`; fixed in 0.0.2 |
| Repository | `Areopaguaworkshop/shutong` master + `2026-11-18-0.0.1-publish`, tag `v0.0.2` | remote tree = local HEAD, 181 files, 17 skills, no corpus or binaries |
| `server.json` | valid, version 0.0.2 | `mcp-publisher validate` → valid |
| Registry entry | blocked | no valid GitHub token; all `pass github/*` return HTTP 401 |

Known metadata defect fixed in 0.0.2: `pymupdf[mupdf-third]` asked for an extra
pymupdf does not define. The dependency is now plain `pymupdf>=1.26.3`.

Registry is the only remaining step:

```bash
pass insert github/shutong-publish      # classic PAT with read:org for the org namespace
cd packages/shutong-backend
mcp-publisher login github --token "$(pass show github/shutong-publish | head -1)"
mcp-publisher publish
```

Known metadata defect for 0.0.2: `pymupdf[mupdf-third]>=1.26.3` asks for an extra that
pymupdf does not define. `uv pip install --dry-run shutong-backend==0.0.1` warns:
`pymupdf==1.27.2.3 does not have an extra named mupdf-third`. Drop the extra.

## Your checklist (only these need a human)

Everything else is prepared: `LICENSE`, `packages/shutong-backend/README.md` with the
`mcp-name:` marker, `pyproject.toml` at 0.0.1 with `readme`, `license`, and
`mcp>=1.27,<2`, plus `packages/shutong-backend/server.json`. `mcp-publisher 1.8.9`
is installed at `~/.local/bin/mcp-publisher`.

1. **Pick the namespace.** Replace `YOURNAME` in two files with your GitHub user or
   org: `packages/shutong-backend/README.md` and `packages/shutong-backend/server.json`.
2. **Create accounts and tokens.**
   - PyPI account + API token (Account settings → API tokens), scope it to the
     `shutong-backend` name or use a project-scoped token after the first upload.
   - GitHub PAT with `read:org` if the namespace is an org; a personal namespace
     works with `mcp-publisher login github` device flow too.
3. **Log in.** `export UV_PUBLISH_TOKEN=pypi-...` and `gh auth login` (or keep the PAT
   in `$GH_PAT`).
4. **Publish PyPI.** From `packages/shutong-backend`: `uv build --no-sources` then
   `uv publish`.
5. **Prove the install.** `uvx shutong-backend-mcp < /dev/null` on a clean machine or
   a fresh `UV_TOOL_DIR`. First run downloads ~13 GB through citeindex.
6. **Publish the registry entry.** `mcp-publisher init` overwrites nothing existing;
   then `mcp-publisher validate`, `mcp-publisher login github --token "$GH_PAT"`,
   `mcp-publisher publish`.
7. **Tag the release.** `git tag v0.0.1 && git push --tags` once the repo has a remote.

Do not re-run `uv publish` with the same version: PyPI rejects a second upload of
0.0.1 permanently.

## Order recap

1. LICENSE, package README with `mcp-name:`, version 0.0.1.
2. Keep `citeindex==0.13.2` declared; document the prerequisite size.
3. `uv build --no-sources`, install the wheel with `uvx`, confirm stdio is clean.
4. `uv publish`, then `uvx shutong-backend-mcp` from the public index.
5. `mcp-publisher validate` then `publish`.
6. Optional npm wrapper, same version number.
