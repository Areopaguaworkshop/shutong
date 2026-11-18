import { test, expect } from "bun:test"
import { chmodSync, mkdirSync, mkdtempSync, readdirSync, rmSync, existsSync, readFileSync, writeFileSync } from "fs"
import path from "path"
import os from "os"
import { initProject } from "../src/cli/init"
import { renderHostArtifacts } from "../src/cli/renderer"
import { addPaperSource, auditPaper, createPaper, paperStatus, usePaper } from "../src/cli/papers"
import { discoverConfig, loadConfig, setupVenvPython, userConfigPath } from "../src/engine/config"
import { setupBackend } from "../src/cli/setup"

const tmpDir = path.join(os.tmpdir(), "shutong-cli-test")
const packagedSkills = path.resolve(import.meta.dir, "../skills")

function skillRootFor(host: string) {
  if (host === "pi") return ".pi/skills"
  if (host === "codex") return ".codex/skills"
  if (host === "claude") return ".claude/skills"
  return ".agents/skills"
}

function writePythonStub(file: string) {
  mkdirSync(path.dirname(file), { recursive: true })
  writeFileSync(file, "#!/bin/sh\nexit 0\n")
  chmodSync(file, 0o755)
}

test("all hosts receive the packaged canonical skills and preserve user files", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "shutong-analysis-hosts-"))
  try {
    for (const host of ["codex", "claude", "opencode", "pi", "hermes"] as const) {
      const project = path.join(root, host)
      renderHostArtifacts(host, project, "python3")
      const skillRoot = skillRootFor(host)
      for (const name of readdirSync(packagedSkills)) {
        const actual = readFileSync(path.join(project, skillRoot, name, "SKILL.md"), "utf8")
        const canonical = readFileSync(path.join(packagedSkills, name, "SKILL.md"), "utf8")
        expect(actual).toBe(canonical)
      }
      const noterSkill = readFileSync(path.join(project, skillRoot, "noter/SKILL.md"), "utf8")
      expect(noterSkill).toContain("## Role")
      expect(noterSkill).toContain("## Tools")
      expect(noterSkill).toContain("shutong_note")
      const verifyCorpus = readFileSync(path.join(project, skillRoot, "verify-corpus/SKILL.md"), "utf8")
      expect(verifyCorpus).toContain("`mode: all`")
      expect(verifyCorpus).not.toContain("action `all`")
      // No agent layer is written for any host; skills carry the role prompts.
      expect(existsSync(path.join(project, ".codex/agents"))).toBe(false)
      expect(existsSync(path.join(project, ".opencode/agents"))).toBe(false)
      expect(existsSync(path.join(project, ".claude/agents"))).toBe(false)
      const custom = path.join(project, skillRoot, "noter/SKILL.md")
      writeFileSync(custom, "Scholar-customized instructions")
      renderHostArtifacts(host, project, "python3")
      expect(readFileSync(custom, "utf8")).toBe("Scholar-customized instructions")
    }
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})

test("packaged role skills match the canonical .agents skill text", () => {
  const canonicalRoot = path.resolve(import.meta.dir, "../../.agents/skills")
  for (const name of ["explore-bibliography", "ingest-source", "noter", "verify-bibliography", "workspace-planner"]) {
    expect(readFileSync(path.join(packagedSkills, name, "SKILL.md"), "utf8")).toBe(readFileSync(path.join(canonicalRoot, name, "SKILL.md"), "utf8"))
  }
  // verify-corpus is intentionally corrected to the published `mode` contract.
  expect(readFileSync(path.join(packagedSkills, "verify-corpus", "SKILL.md"), "utf8")).toContain("`mode: all`")
})

test("initProject creates a local OpenCode integration", () => {
  mkdirSync(path.join(tmpDir, ".opencode"), { recursive: true })
  const result = initProject(tmpDir, true, "opencode")
  expect(existsSync(path.join(tmpDir, ".shutong", "config.toml"))).toBe(true)
  expect(JSON.parse(readFileSync(path.join(tmpDir, ".shutong", "glossary", "theology-en-zh.json"), "utf8")).hypostasis).toBe("位格")
  expect(existsSync(path.join(tmpDir, ".agents", "skills", "cite-research", "SKILL.md"))).toBe(true)
  expect(existsSync(path.join(tmpDir, ".agents", "skills", "shutong-research", "SKILL.md"))).toBe(true)
  expect(JSON.parse(readFileSync(path.join(tmpDir, "opencode.json"), "utf8")).mcp.servers.shutong).toBeDefined()
  const agents = readFileSync(path.join(tmpDir, "AGENTS.md"), "utf8")
  expect(agents).toContain("<!-- SHUTONG:BEGIN")
  expect(agents).not.toContain("SHUTONG:CORPUS")
  expect(agents).not.toContain("@ingestor")
  expect(agents).not.toContain("Bibliographer")
  expect(agents).toContain("`explore-bibliography`")
  expect(result.written.length).toBeGreaterThan(0)
  rmSync(tmpDir, { recursive: true, force: true })
})

test("initProject updates an existing OpenCode JSONC config and preserves comments", () => {
  mkdirSync(tmpDir, { recursive: true })
  writeFileSync(path.join(tmpDir, "opencode.jsonc"), "// OpenCode\n{\n  \"theme\": \"dark\",\n  \"mcp\": { \"servers\": { \"existing\": { \"type\": \"remote\", \"url\": \"https://example.invalid\" } } }\n}\n")
  initProject(tmpDir, false, "opencode")
  expect(existsSync(path.join(tmpDir, "opencode.json"))).toBe(false)
  const raw = readFileSync(path.join(tmpDir, "opencode.jsonc"), "utf8")
  expect(raw.startsWith("// OpenCode\n")).toBe(true)
  const config = Bun.JSONC.parse(raw) as any
  expect(config.mcp.servers.shutong).toBeDefined()
  expect(config.mcp.servers.existing.url).toBe("https://example.invalid")
  expect(config.theme).toBe("dark")
  rmSync(tmpDir, { recursive: true, force: true })
})

test("initProject uses the configured Python executable for MCP", () => {
  mkdirSync(path.join(tmpDir, ".opencode"), { recursive: true })
  mkdirSync(path.join(tmpDir, ".shutong"), { recursive: true })
  writeFileSync(path.join(tmpDir, ".shutong", "config.toml"), "[backend]\npython = \"/opt/shutong/bin/python\"\n")
  initProject(tmpDir, false, "opencode")
  expect(JSON.parse(readFileSync(path.join(tmpDir, "opencode.json"), "utf8")).mcp.servers.shutong.command[0]).toBe("/opt/shutong/bin/python")
  rmSync(tmpDir, { recursive: true, force: true })
})

test("initProject creates all five host integrations", () => {
  const hosts = [
    ["opencode", ".agents/skills/corpus-status/SKILL.md"],
    ["claude", ".claude/skills/corpus-status/SKILL.md"],
    ["codex", ".codex/config.toml"],
    ["pi", ".pi/skills/corpus-status/SKILL.md"],
    ["hermes", ".hermes/SHUTONG-MCP.md"],
  ] as const
  for (const [host, artifact] of hosts) {
    const root = path.join(tmpDir, host)
    initProject(root, false, host)
    expect(existsSync(path.join(root, artifact))).toBe(true)
    const skillRoot = skillRootFor(host)
    expect(existsSync(path.join(root, skillRoot, "paper-workspace/SKILL.md"))).toBe(true)
    expect(existsSync(path.join(root, skillRoot, "shutong-research/SKILL.md"))).toBe(true)
    expect(existsSync(path.join(root, skillRoot, "explore-bibliography/SKILL.md"))).toBe(true)
    // No host receives agent definitions; the surface is MCP plus skills.
    for (const agents of [".codex/agents", ".opencode/agents", ".claude/agents"]) expect(existsSync(path.join(root, agents))).toBe(false)
    if (host === "opencode") expect(JSON.parse(readFileSync(path.join(root, "opencode.json"), "utf8")).default_agent).toBeUndefined()
    if (host === "claude") expect(existsSync(path.join(root, "CLAUDE.md"))).toBe(true)
    if (host === "pi") {
      const piMcp = JSON.parse(readFileSync(path.join(root, ".pi", "mcp.json"), "utf8"))
      expect(typeof piMcp.mcpServers.shutong.command).toBe("string")
      expect(piMcp.mcpServers.shutong.command.length).toBeGreaterThan(0)
      expect(piMcp.mcpServers.shutong.args).toEqual(["-m", "shutong_backend.mcp_server"])
    }
  }
  rmSync(tmpDir, { recursive: true, force: true })
})

test("initProject is idempotent without force", () => {
  mkdirSync(path.join(tmpDir, ".opencode"), { recursive: true })
  initProject(tmpDir, false, "opencode")
  const second = initProject(tmpDir, false, "opencode")
  expect(second.written.length).toBe(0)
  rmSync(tmpDir, { recursive: true, force: true })
})

test("initProject lists a warning and exits when no host is detected", () => {
  mkdirSync(tmpDir, { recursive: true })
  const result = initProject(tmpDir, false)
  expect(result.warnings[0]).toContain("No supported agent hosts")
  expect(existsSync(path.join(tmpDir, "corpus"))).toBe(false)
  rmSync(tmpDir, { recursive: true, force: true })
})

test("fresh init uses the setup interpreter persisted in user config", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "shutong-init-setup-"))
  const previousConfigHome = process.env.XDG_CONFIG_HOME
  const previousDataHome = process.env.XDG_DATA_HOME
  try {
    process.env.XDG_CONFIG_HOME = path.join(root, "config")
    process.env.XDG_DATA_HOME = path.join(root, "data")
    const python = path.join(root, "data", "shutong", "venv", "bin", "python")
    writePythonStub(python)
    mkdirSync(path.dirname(userConfigPath()), { recursive: true })
    writeFileSync(userConfigPath(), `[backend]\npython = "${python}"\n`)
    const project = path.join(root, "project")
    initProject(project, false, "opencode")
    const config = JSON.parse(readFileSync(path.join(project, "opencode.json"), "utf8"))
    expect(config.mcp.servers.shutong.command[0]).toBe(python)
    // A project scaffold must not persist the inferred default and shadow user config.
    expect(readFileSync(path.join(project, ".shutong", "config.toml"), "utf8")).not.toContain("[backend]")
  } finally {
    if (previousConfigHome === undefined) delete process.env.XDG_CONFIG_HOME
    else process.env.XDG_CONFIG_HOME = previousConfigHome
    if (previousDataHome === undefined) delete process.env.XDG_DATA_HOME
    else process.env.XDG_DATA_HOME = previousDataHome
    rmSync(root, { recursive: true, force: true })
  }
})

test("absent defaults do not shadow an explicit user interpreter", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "shutong-discover-"))
  const previousConfigHome = process.env.XDG_CONFIG_HOME
  try {
    process.env.XDG_CONFIG_HOME = path.join(root, "config")
    const python = path.join(root, "user-venv", "bin", "python")
    mkdirSync(path.dirname(userConfigPath()), { recursive: true })
    writeFileSync(userConfigPath(), `[backend]\npython = "${python}"\n`)
    const project = path.join(root, "project")
    mkdirSync(path.join(project, ".shutong"), { recursive: true })
    writeFileSync(path.join(project, ".shutong", "config.toml"), "[project]\ncorpus_root = \"corpus\"\nlibrary_root = \"library\"\n")
    const config = loadConfig(userConfigPath())
    expect(config.python_bin).toBe(python)
    expect(discoverConfig(project).python_bin).toBe(python)
  } finally {
    if (previousConfigHome === undefined) delete process.env.XDG_CONFIG_HOME
    else process.env.XDG_CONFIG_HOME = previousConfigHome
    rmSync(root, { recursive: true, force: true })
  }
})

test("setup venv interpreter is inferred when no config is present", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "shutong-setup-infer-"))
  const previousDataHome = process.env.XDG_DATA_HOME
  try {
    process.env.XDG_DATA_HOME = root
    const python = setupVenvPython()
    writePythonStub(python)
    expect(loadConfig(path.join(root, "missing.toml")).python_bin).toBe(python)
  } finally {
    if (previousDataHome === undefined) delete process.env.XDG_DATA_HOME
    else process.env.XDG_DATA_HOME = previousDataHome
    rmSync(root, { recursive: true, force: true })
  }
})

const systemPython = Bun.which("python3")
const pythonVersion = systemPython ? new TextDecoder().decode(Bun.spawnSync([systemPython, "--version"]).stdout) : ""
const hasPython312 = /Python 3\.(1[2-9]|[2-9]\d)/.test(pythonVersion)

test.skipIf(!hasPython312)("setupBackend persists the created interpreter to user config", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "shutong-setup-persist-"))
  const previousConfigHome = process.env.XDG_CONFIG_HOME
  const previousDataHome = process.env.XDG_DATA_HOME
  try {
    process.env.XDG_CONFIG_HOME = path.join(root, "config")
    process.env.XDG_DATA_HOME = path.join(root, "data")
    writePythonStub(setupVenvPython())
    const result = setupBackend()
    expect(result.ok).toBe(true)
    expect(result.python).toBe(setupVenvPython())
    expect(readFileSync(userConfigPath(), "utf8")).toContain(setupVenvPython())
  } finally {
    if (previousConfigHome === undefined) delete process.env.XDG_CONFIG_HOME
    else process.env.XDG_CONFIG_HOME = previousConfigHome
    if (previousDataHome === undefined) delete process.env.XDG_DATA_HOME
    else process.env.XDG_DATA_HOME = previousDataHome
    rmSync(root, { recursive: true, force: true })
  }
})

test("paper workspace keeps source membership and audits roles", () => {
  const root = path.join(tmpDir, "paper")
  createPaper(root, "nicea", "Nicaea", "How did doctrine develop?")
  addPaperSource(root, "nicea", "athanasius", "primary")
  addPaperSource(root, "nicea", "ayres", "secondary")
  usePaper(root, "nicea")
  expect(paperStatus(root)?.sources).toHaveLength(2)
  expect(auditPaper(root)).toMatchObject({ status: "ok", paper_id: "nicea" })
  rmSync(path.join(tmpDir, "paper"), { recursive: true, force: true })
})
