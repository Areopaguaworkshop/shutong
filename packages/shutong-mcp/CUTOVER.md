# Cutover guide

## Preconditions

```bash
node dist/index.js doctor
```

All checks must pass: Node ≥24, `citeindex` on PATH (or `SHUTONG_CITEINDEX_BIN`),
PyYAML, corpus root, built index, LLM endpoint and host configs.

## Install one host

```bash
node dist/index.js install --host opencode
node dist/index.js install --host claude
node dist/index.js install --host codex
node dist/index.js install --host pi
```

Each install:

- backs up the existing config to `<config>.shutong-backup-<timestamp>`
- writes the `shutong` MCP entry
- records the path/backup in `~/.shutong/mcp-install.json`

`--no-backup` skips the backup; `--dry-run` reports without writing.
Hermes is never modified; `install --host hermes` prints the YAML to add.

## Smoke test

Restart the host, then call:

```text
shutong_corpus status
shutong_search query=尼西亚
shutong_verify mode=all
```

Expect 280 documents / 98,664 nodes, search hits, and 0 integrity failures.

## Rollback

```bash
node dist/index.js rollback
```

Restores every backup recorded in `~/.shutong/mcp-install.json`; configs created
by the installer are removed. `rollback --dry-run` only reports.

The Python MCP server remains available as a manual fallback:

```toml
[mcp_servers.shutong_python]
command = "python3"
args = ["-m", "shutong_backend.mcp_server"]
```

## Publish

`npm publish` is intentionally not automated here. Run it from a credentialed
release environment after `npm pack --dry-run` and the smoke tests pass.
