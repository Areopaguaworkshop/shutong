# Publishing Shutong as an MCP server — 0.0.3

This guide covers the 0.0.3 release. Both 0.0.3 packages are published and the
launcher is verified from a clean install; keep the release order below for future
versions.

## Two PyPI distributions, one server

The MCP Registry identifies a server by the package whose **binary** it launches.
`server.json` has no field for choosing a script, and `runtimeArguments` are
unproven and non-portable across registry clients. The registry therefore cannot
point at `shutong-backend` and ask for its `shutong-backend-mcp` script.

The supported layout is two distributions:

| Artifact | Registry | Identifier | Version | Status |
| --- | --- | --- | --- | --- |
| Backend + MCP implementation | PyPI | `shutong-backend` | 0.0.3 | published |
| Thin launcher | PyPI | `shutong-backend-mcp` | 0.0.3 | published |
| Registry metadata | MCP Registry | `io.github.Areopaguaworkshop/shutong` | 0.0.3 | validated, not published |

`packages/shutong-backend-mcp/` declares the exact dependency
`shutong-backend==0.0.3` and exposes the same console script
`shutong-backend-mcp = shutong_backend.mcp_server:cli`. It ships no server code;
the entry-point module comes from the backend dependency. `server.json` names
`shutong-backend-mcp` because that is the package whose console script the
registry launches.

Both package READMEs must contain the ownership marker:

```text
<!-- mcp-name: io.github.Areopaguaworkshop/shutong -->
```

## Release order

Each step gates the next. Do not publish registry metadata before both PyPI
packages are live.

### 1. Backend 0.0.3

The parent release bumps `packages/shutong-backend/pyproject.toml` to `0.0.3`
before this step. Build, smoke-test, then publish:

```bash
cd packages/shutong-backend
rm -rf dist
uv build --no-sources          # required: repo root declares a path source
ls dist/                       # wheel + sdist

UV_PUBLISH_TOKEN=pypi-... uv publish
```

Confirm the distribution exists in the public index before continuing:

```bash
uvx --from 'shutong-backend==0.0.3' shutong-backend-mcp < /dev/null
```

### 2. Launcher 0.0.3

```bash
cd packages/shutong-backend-mcp
rm -rf dist
uv build --no-sources
ls dist/                       # wheel + sdist

UV_PUBLISH_TOKEN=pypi-... uv publish
```

`uv build` does not resolve runtime dependencies, so building the launcher before
backend 0.0.3 is on PyPI is fine. Installing it is not: the exact pin only
resolves after step 1.

### 3. Prove the public install

```bash
uvx shutong-backend-mcp < /dev/null
uvx --from 'shutong-backend-mcp==0.0.3' shutong-backend-mcp < /dev/null
```

Stdout must stay clean — any banner corrupts JSON-RPC. The first run downloads
roughly 13 GB through `citeindex`; use a fresh `UV_TOOL_DIR` to test the cold path.

### 4. Publish registry metadata

```bash
# publisher v1.8.9
curl -L https://github.com/modelcontextprotocol/registry/releases/download/v1.8.9/mcp-publisher_linux_amd64.tar.gz \
  | tar xz -C /tmp/opencode mcp-publisher && install -Dm755 /tmp/opencode/mcp-publisher ~/.local/bin/mcp-publisher

cd packages/shutong-backend
mcp-publisher login github --token "$GH_PAT"   # org namespaces need a PAT, not the device flow
mcp-publisher validate
mcp-publisher publish
```

Do **not** run `mcp-publisher init` in `packages/shutong-backend`: it would
overwrite the maintained `server.json`. Run it only in a scratch directory if you
need a reference file.

`server.json` for 0.0.3:

```json
{
  "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
  "name": "io.github.Areopaguaworkshop/shutong",
  "title": "Shutong",
  "description": "Citation-verified scholarly research over a local corpus",
  "repository": {
    "url": "https://github.com/Areopaguaworkshop/shutong",
    "source": "github"
  },
  "version": "0.0.3",
  "packages": [{
    "registryType": "pypi",
    "identifier": "shutong-backend-mcp",
    "version": "0.0.3",
    "runtimeHint": "uvx",
    "transport": { "type": "stdio" },
    "environmentVariables": [
      { "name": "SHUTONG_CORPUS_ROOT", "description": "Absolute path to the corpus root", "format": "string", "isRequired": false },
      { "name": "SHUTONG_LIBRARY_ROOT", "description": "Absolute path to the library root", "format": "string", "isRequired": false }
    ]
  }]
}
```

### Validation

`mcp-publisher validate` passed on this machine after both PyPI uploads. For a
future version, run it only after both packages are public; a failure naming the
missing version is index lag, while a marker or identifier error is a real defect.

Rules that reject a publish: description over 100 characters, a range as version,
`"version": "latest"`, package not yet public, missing `mcp-name:` marker, or a
registry host other than `pypi.org` / `registry.npmjs.org`.

## PyPI authentication

Both 0.0.3 packages are public. Keep one project-scoped token per distribution
(Account settings → API tokens) for the next upload:

```bash
export UV_PUBLISH_TOKEN=pypi-...
```

PyPI refuses a second upload of the same version permanently, so burn a new
version number for every metadata fix.

## Prerequisite: citeindex

`shutong-backend` depends on `citeindex==0.13.2`, a separate upstream project on
PyPI. It pulls paddlepaddle, mineru, whisperx, pyannote and playwright, so the
first install is about 13 GB. Shutong does not vendor, fork, or copy it. The
launcher inherits the dependency transitively and does not restate it. A network
connection is required on the first `uvx` run.

## Host configuration

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

OMP has no `omp mcp` subcommand; use the in-TUI `/mcp add`, then `/mcp reload`,
`/mcp list`, `/mcp test shutong`. Both hosts run stdio servers launched through
`uvx`.

## Local build validation

Run in each package tree; no network publish:

```bash
cd packages/shutong-backend && uv build --no-sources
cd packages/shutong-backend-mcp && uv build --no-sources
```

Inspect the launcher wheel:

```bash
unzip -p dist/shutong_backend_mcp-0.0.3-py3-none-any.whl \
  '*/entry_points.txt'            # shutong-backend-mcp = shutong_backend.mcp_server:cli
unzip -p dist/shutong_backend_mcp-0.0.3-py3-none-any.whl \
  '*/METADATA' | grep -E '^(Name|Version|Requires-Python|Requires-Dist)'
# Requires-Dist: shutong-backend==0.0.3
```

Parse the registry file:

```bash
python -m json.tool packages/shutong-backend/server.json > /dev/null
```

## Version discipline

Keep `server.json.version` == `packages[].version` == launcher
`pyproject.toml.version` == backend `pyproject.toml.version` == git tag `v0.0.3`.
PyPI files are immutable per version, and registry entries are immutable per
version string, so every metadata fix costs a new number.

## Checklist (human steps)

1. Bump `packages/shutong-backend/pyproject.toml` to `0.0.3` and release it as
   `shutong-backend` 0.0.3.
2. Confirm `shutong-backend==0.0.3` installs from PyPI.
3. Build and publish `packages/shutong-backend-mcp` as `shutong-backend-mcp`
   0.0.3.
4. Prove `uvx shutong-backend-mcp` and `uvx --from shutong-backend-mcp==0.0.3`.
5. Only then `mcp-publisher validate` and `mcp-publisher publish`.
6. Tag `v0.0.3` after the registry entry is live.
