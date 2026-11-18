import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { hermesInstructions, installHost, rollbackAll } from "../src/commands/install.ts";

test("host installers write idempotent MCP entries", () => {
  const home = mkdtempSync(path.join(os.tmpdir(), "shutong-install-"));
  try {
    installHost("opencode", home);
    installHost("opencode", home);
    const opencode = JSON.parse(
      readFileSync(path.join(home, ".config", "opencode", "opencode.json"), "utf8"),
    );
    assert.ok(Array.isArray(opencode.mcp.servers.shutong.command));

    installHost("claude", home);
    const claude = JSON.parse(readFileSync(path.join(home, ".claude.json"), "utf8"));
    assert.ok(claude.mcpServers.shutong.command);

    installHost("codex", home);
    installHost("codex", home);
    const codex = readFileSync(path.join(home, ".codex", "config.toml"), "utf8");
    assert.equal(codex.split("[mcp_servers.shutong]").length - 1, 1);

    installHost("pi", home);
    const pi = JSON.parse(readFileSync(path.join(home, ".pi", "mcp.json"), "utf8"));
    assert.ok(pi.mcpServers.shutong.command);

    assert.match(hermesInstructions(), /mcp_servers/);

    const existing = path.join(home, ".config", "opencode", "opencode.json");
    mkdirSync(path.dirname(existing), { recursive: true });
    writeFileSync(existing, JSON.stringify({ existing: true }), "utf8");
    installHost("opencode", home);
    assert.ok(JSON.parse(readFileSync(existing, "utf8")).mcp);
    rollbackAll(home);
    assert.equal(JSON.parse(readFileSync(existing, "utf8")).existing, true);
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});
