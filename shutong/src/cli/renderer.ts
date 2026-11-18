import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "fs"
import path from "path"
import type { Host } from "./hosts"

const commandTemplates: Record<string, string> = {
  research: "Search the local corpus for: $ARGUMENTS\n\nUse cite-research and verify every cited passage.\n",
  ingest: "Ingest this source: $ARGUMENTS\n\nUse ingest-source, then confirm searchability.\n",
  verify: "Verify this source or node hash: $ARGUMENTS\n\nUse verify-corpus.\n",
  corpus: "Use corpus-status.\n",
  paper: "Manage a paper workspace: $ARGUMENTS\n\nUse paper-workspace. Never use sources outside the active paper unless the user explicitly requests a library-wide search.\n",
}

function writeIfMissing(file: string, content: string, force: boolean, written: string[]) {
  if (!force && existsSync(file)) return
  mkdirSync(path.dirname(file), { recursive: true })
  writeFileSync(file, content, "utf8")
  written.push(file)
}

function pythonEnv() {
  return { SHUTONG_CORPUS_ROOT: "./corpus", SHUTONG_LIBRARY_ROOT: "./library", SHUTONG_GLOSSARY_DIR: "./.shutong/glossary" }
}

/** Preserve a leading JSONC comment block (and blank lines) when rewriting a config file. */
function leadingCommentBlock(text: string): string {
  const match = /^\s*((?:\/\/[^\n]*\n|\/\*[\s\S]*?\*\/\s*\n|\s*\n)+)(?=\{)/.exec(text)
  return match ? match[1] : ""
}

function mergeJson(file: string, key: string, value: Record<string, unknown>, force: boolean, written: string[]) {
  const original = existsSync(file) ? readFileSync(file, "utf8") : ""
  const current = original ? Bun.JSONC.parse(original) as Record<string, any> : {}
  current[key] ??= {}
  if (!force && current[key].shutong) return
  current[key].shutong = value.shutong
  mkdirSync(path.dirname(file), { recursive: true })
  writeFileSync(file, `${leadingCommentBlock(original)}${JSON.stringify(current, null, 2)}\n`, "utf8")
  written.push(file)
}

function mergeOpenCodeMcp(file: string, server: Record<string, unknown>, force: boolean, written: string[]) {
  const original = existsSync(file) ? readFileSync(file, "utf8") : ""
  const current = original ? Bun.JSONC.parse(original) as Record<string, any> : {}
  current.mcp ??= {}
  current.mcp.servers ??= {}
  if (!force && current.mcp.servers.shutong) return
  current.mcp.servers.shutong = server
  mkdirSync(path.dirname(file), { recursive: true })
  writeFileSync(file, `${leadingCommentBlock(original)}${JSON.stringify(current, null, 2)}\n`, "utf8")
  written.push(file)
}

function renderCodexMcp(pythonBin: string) {
  const quote = (value: string) => JSON.stringify(value)
  return `\n[mcp_servers.shutong]\ncommand = ${quote(pythonBin)}\nargs = [${quote("-m")}, ${quote("shutong_backend.mcp_server")}]\n\n[mcp_servers.shutong.env]\nSHUTONG_CORPUS_ROOT = ${quote("./corpus")}\nSHUTONG_LIBRARY_ROOT = ${quote("./library")}\nSHUTONG_GLOSSARY_DIR = ${quote("./.shutong/glossary")}\n`
}

function renderHermesInstructions(pythonBin: string) {
  return `# Shutong MCP (local-only setup)\n\nShutong does not modify global Hermes settings. To enable this project, add the following to \`~/.hermes/config.yaml\` yourself:\n\n\`\`\`yaml\nmcp_servers:\n  shutong:\n    command: ${pythonBin}\n    args: ["-m", "shutong_backend.mcp_server"]\n    env:\n      SHUTONG_CORPUS_ROOT: ./corpus\n      SHUTONG_LIBRARY_ROOT: ./library\n      SHUTONG_GLOSSARY_DIR: ./.shutong/glossary\n\`\`\`\n`
}

/** Canonical role skills shipped inside the npm package. */
function canonicalSkillRoot(): string {
  const candidates = [
    path.resolve(import.meta.dir, "../../skills"),
    path.resolve(import.meta.dir, "../../../.agents/skills"),
  ]
  const found = candidates.find((candidate) => existsSync(path.join(candidate, "noter/SKILL.md")))
  if (!found) throw new Error("Shutong skill templates are missing; rebuild or reinstall the package.")
  return found
}

function canonicalSkills(): Array<[string, string]> {
  const root = canonicalSkillRoot()
  return readdirSync(root, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && existsSync(path.join(root, entry.name, "SKILL.md")))
    .map((entry) => [entry.name, readFileSync(path.join(root, entry.name, "SKILL.md"), "utf8")] as [string, string])
}

function hostSkillRoot(host: Host): string {
  if (host === "pi") return ".pi/skills"
  if (host === "codex") return ".codex/skills"
  if (host === "claude") return ".claude/skills"
  return ".agents/skills"
}

export function renderHostArtifacts(host: Host, root: string, pythonBin: string, force = false): string[] {
  const written: string[] = []
  const skillRoot = hostSkillRoot(host)
  for (const [name, content] of canonicalSkills()) writeIfMissing(path.join(root, skillRoot, name, "SKILL.md"), content, force, written)
  if (host === "opencode" || host === "claude") {
    const commandRoot = host === "opencode" ? ".opencode/commands" : ".claude/commands"
    for (const [name, content] of Object.entries(commandTemplates)) writeIfMissing(path.join(root, commandRoot, `${name}.md`), content, force, written)
  }
  if (host === "claude") {
    writeIfMissing(path.join(root, "CLAUDE.md"), "# Shutong\n\nYou are Shutong, the primary scholar-workflow conductor. Read and follow `AGENTS.md` before acting.\n", force, written)
  }
  if (host === "opencode") {
    const jsonc = path.join(root, "opencode.jsonc")
    mergeOpenCodeMcp(
      existsSync(jsonc) ? jsonc : path.join(root, "opencode.json"),
      { type: "local", command: [pythonBin, "-m", "shutong_backend.mcp_server"], environment: pythonEnv() },
      force,
      written,
    )
  }
  if (host === "claude") mergeJson(path.join(root, ".mcp.json"), "mcpServers", { shutong: { command: pythonBin, args: ["-m", "shutong_backend.mcp_server"], env: pythonEnv() } }, force, written)
  if (host === "pi") mergeJson(path.join(root, ".pi", "mcp.json"), "mcpServers", { shutong: { command: pythonBin, args: ["-m", "shutong_backend.mcp_server"], env: pythonEnv() } }, force, written)
  if (host === "codex") {
    const file = path.join(root, ".codex", "config.toml")
    const current = existsSync(file) ? readFileSync(file, "utf8") : ""
    if (!current.includes("[mcp_servers.shutong]")) { mkdirSync(path.dirname(file), { recursive: true }); writeFileSync(file, `${current.trimEnd()}${renderCodexMcp(pythonBin)}`, "utf8"); written.push(file) }
  }
  if (host === "hermes") writeIfMissing(path.join(root, ".hermes", "SHUTONG-MCP.md"), renderHermesInstructions(pythonBin), force, written)
  return written
}
