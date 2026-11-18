# Shutong backend

<!-- mcp-name: io.github.Areopaguaworkshop/shutong -->

MCP server and scholarly backend for Shutong. Citation-verified research over a
local corpus: search, Merkle verification, bibliography checkpoints, notes,
claims, audits, and DOCX export.

## Run the MCP server

```bash
uvx shutong-backend-mcp
```

The server speaks stdio. Configure a corpus path with `SHUTONG_CORPUS_ROOT`.

## Prerequisites

- Python 3.12 or newer. `uvx` downloads it when missing.
- `citeindex` is a separate project that Shutong depends on. It brings
  paddlepaddle, mineru, whisperx, pyannote and playwright, so the first install
  is about 13 GB and needs a network connection. Shutong does not vendor or fork
  it.
- For ingestion you also need the models citeindex downloads on first use.

## Host configuration

Claude Desktop:

```json
{ "mcpServers": { "shutong": { "command": "uvx", "args": ["shutong-backend-mcp"],
  "env": { "SHUTONG_CORPUS_ROOT": "/abs/path/to/corpus" } } } }
```

OpenCode V2 (`opencode.json`):

```json
{ "mcp": { "servers": { "shutong": { "type": "local",
  "command": ["uvx", "shutong-backend-mcp"],
  "environment": { "SHUTONG_CORPUS_ROOT": "/abs/path/to/corpus" } } } } }
```

Codex (`~/.codex/config.toml`):

```toml
[mcp_servers.shutong]
command = "uvx"
args = ["shutong-backend-mcp"]
env = { SHUTONG_CORPUS_ROOT = "/abs/path/to/corpus" }
```

## Setup and diagnostics

```bash
shutong-backend init      # scaffold AGENTS.md, corpus/, library/
shutong-backend doctor    # Ollama, citeindex, GROBID, corpus
shutong-backend doctor --surface   # MCP tools, skill pack, no agent layer
```

## License

MIT.
