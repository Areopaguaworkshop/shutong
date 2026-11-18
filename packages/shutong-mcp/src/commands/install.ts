import { copyFileSync, existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";

export type Host = "opencode" | "claude" | "codex" | "pi" | "hermes";

export const HOSTS: Host[] = ["opencode", "claude", "codex", "pi", "hermes"];

export interface InstallOptions {
  dryRun?: boolean;
  backup?: boolean;
}

export interface InstallResult {
  host: Host;
  path: string;
  backup?: string | null;
  existed: boolean;
}

export function shutongHome(): string {
  return process.env.SHUTONG_HOME ?? os.homedir();
}

function commandSpec(): { command: string; args: string[] } {
  const script = path.resolve(process.argv[1] ?? path.join(import.meta.dirname, "index.js"));
  if (script.endsWith(".ts")) {
    return { command: process.execPath, args: [script] };
  }
  return { command: script, args: [] };
}

function readJson(file: string): Record<string, any> {
  if (!existsSync(file)) return {};
  try {
    return JSON.parse(readFileSync(file, "utf8"));
  } catch {
    return {};
  }
}

function writeJson(file: string, value: unknown, dryRun: boolean): void {
  if (dryRun) return;
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function backupFile(file: string, dryRun: boolean): string | null {
  if (!existsSync(file)) return null;
  const backup = `${file}.shutong-backup-${new Date().toISOString().replace(/[:.]/g, "-")}`;
  if (!dryRun) copyFileSync(file, backup);
  return backup;
}

function tomlBlock(): string {
  const spec = commandSpec();
  const quote = (value: string) => JSON.stringify(value);
  const args = spec.args.length ? `args = [${spec.args.map(quote).join(", ")}]` : null;
  return ["[mcp_servers.shutong]", `command = ${quote(spec.command)}`, ...(args ? [args] : []), ""].join("\n");
}

export function installHost(
  host: Host,
  home = shutongHome(),
  options: InstallOptions = {},
): InstallResult {
  const dryRun = options.dryRun ?? false;
  const shouldBackup = options.backup ?? true;
  const spec = commandSpec();

  if (host === "opencode") {
    const file = path.join(home, ".config", "opencode", "opencode.json");
    const existed = existsSync(file);
    const backup = shouldBackup ? backupFile(file, dryRun) : null;
    const config = readJson(file);
    config.mcp ??= {};
    config.mcp.servers ??= {};
    config.mcp.servers.shutong = {
      type: "local",
      command: [spec.command, ...spec.args],
      enabled: true,
    };
    writeJson(file, config, dryRun);
    return { host, path: file, backup, existed };
  }
  if (host === "claude") {
    const file = path.join(home, ".claude.json");
    const existed = existsSync(file);
    const backup = shouldBackup ? backupFile(file, dryRun) : null;
    const config = readJson(file);
    config.mcpServers ??= {};
    config.mcpServers.shutong = { command: spec.command, args: spec.args };
    writeJson(file, config, dryRun);
    return { host, path: file, backup, existed };
  }
  if (host === "pi") {
    const file = path.join(home, ".pi", "mcp.json");
    const existed = existsSync(file);
    const backup = shouldBackup ? backupFile(file, dryRun) : null;
    const config = readJson(file);
    config.mcpServers ??= {};
    config.mcpServers.shutong = { command: spec.command, args: spec.args };
    writeJson(file, config, dryRun);
    return { host, path: file, backup, existed };
  }
  if (host === "codex") {
    const file = path.join(home, ".codex", "config.toml");
    const existed = existsSync(file);
    const backup = shouldBackup ? backupFile(file, dryRun) : null;
    const current = existsSync(file) ? readFileSync(file, "utf8") : "";
    if (!current.includes("[mcp_servers.shutong]")) {
      if (!dryRun) {
        mkdirSync(path.dirname(file), { recursive: true });
        writeFileSync(file, `${current.trimEnd()}\n\n${tomlBlock()}`, "utf8");
      }
    }
    return { host, path: file, backup, existed };
  }
  return { host, path: path.join(home, ".hermes", "SHUTONG-MCP.md"), backup: null, existed: false };
}

function manifestPath(home: string): string {
  return path.join(home, ".shutong", "mcp-install.json");
}

export function installAll(
  hosts: Host[],
  options: { home?: string; dryRun?: boolean; backup?: boolean } = {},
): InstallResult[] {
  const home = options.home ?? shutongHome();
  const results = hosts.map((host) => installHost(host, home, options));
  if (!options.dryRun) {
    const manifest = readJson(manifestPath(home));
    for (const result of results) {
      if (result.host === "hermes") continue;
      manifest[result.host] = {
        path: result.path,
        backup: result.backup ?? null,
        existed: result.existed,
      };
    }
    writeJson(manifestPath(home), manifest, false);
  }
  return results;
}

export function rollbackAll(home = shutongHome(), dryRun = false): Array<{ host: string; path: string; restored: boolean }> {
  const manifest = readJson(manifestPath(home));
  const results: Array<{ host: string; path: string; restored: boolean }> = [];
  for (const [host, record] of Object.entries(manifest)) {
    const pathValue = (record as any)?.path;
    if (typeof pathValue !== "string") continue;
    const backup = (record as any)?.backup;
    const existed = (record as any)?.existed === true;
    if (typeof backup === "string" && existsSync(backup)) {
      if (!dryRun) copyFileSync(backup, pathValue);
      results.push({ host, path: pathValue, restored: true });
    } else if (!existed && existsSync(pathValue)) {
      if (!dryRun) unlinkSync(pathValue);
      results.push({ host, path: pathValue, restored: true });
    } else {
      results.push({ host, path: pathValue, restored: false });
    }
  }
  if (!dryRun && existsSync(manifestPath(home))) unlinkSync(manifestPath(home));
  return results;
}

export function hermesInstructions(): string {
  const spec = commandSpec();
  return [
    "# Shutong MCP",
    "",
    "Add this to your Hermes MCP configuration:",
    "",
    "```yaml",
    "mcp_servers:",
    "  shutong:",
    `    command: ${JSON.stringify(spec.command)}`,
    spec.args.length ? `    args: [${spec.args.map((arg) => JSON.stringify(arg)).join(", ")}]` : "    args: []",
    "```",
    "",
  ].join("\n");
}
