import { test, expect } from "bun:test"
import { mkdirSync, mkdtempSync, rmSync, existsSync, readFileSync, writeFileSync } from "fs"
import path from "path"
import os from "os"
import { initProject } from "../src/cli/init"
import { renderHostArtifacts } from "../src/cli/renderer"
import { addPaperSource, auditPaper, createPaper, paperStatus, usePaper } from "../src/cli/papers"

const tmpDir = path.join(os.tmpdir(), "shutong-cli-test")

test("all hosts receive packaged analysis skills and preserve user files", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "shutong-analysis-hosts-"))
  try {
    for (const host of ["codex", "claude", "opencode", "pi", "hermes"] as const) {
      const project = path.join(root, host)
      renderHostArtifacts(host, project, "python3")
      const skillRoot = host === "codex" ? ".codex/skills" : host === "pi" ? ".pi/skills" : ".agents/skills"
      for (const name of ["analysis-plan", "text-analysis", "evidence-synthesis", "citation-check"]) {
        const actual = readFileSync(path.join(project, skillRoot, name, "SKILL.md"), "utf8")
        const canonical = readFileSync(path.resolve(import.meta.dir, "../../packages/shutong-backend/shutong_backend/templates/skills", name, "SKILL.md"), "utf8")
        expect(actual).toBe(canonical)
        expect(actual.startsWith(`---\nname: ${name}\n`)).toBe(true)
      }
      expect(readFileSync(path.join(project, skillRoot, "noter/SKILL.md"), "utf8")).toContain("name: noter")
      // No agent layer is written for any host; skills carry the role prompts.
      expect(existsSync(path.join(project, ".codex/agents"))).toBe(false)
      expect(existsSync(path.join(project, ".opencode/agents"))).toBe(false)
      expect(existsSync(path.join(project, ".claude/agents"))).toBe(false)
      const noterSkill = readFileSync(path.join(project, skillRoot, "noter/SKILL.md"), "utf8")
      expect(noterSkill).toContain("text-analysis")
      const custom = path.join(project, skillRoot, "text-analysis/SKILL.md")
      writeFileSync(custom, "Scholar-customized instructions")
      renderHostArtifacts(host, project, "python3")
      expect(readFileSync(custom, "utf8")).toBe("Scholar-customized instructions")
    }
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})

test("initProject creates a local OpenCode integration", () => {
  mkdirSync(path.join(tmpDir, ".opencode"), { recursive: true })
  const result = initProject(tmpDir, true, "opencode")
  expect(existsSync(path.join(tmpDir, ".shutong", "config.toml"))).toBe(true)
  expect(JSON.parse(readFileSync(path.join(tmpDir, ".shutong", "glossary", "theology-en-zh.json"), "utf8")).hypostasis).toBe("位格")
  expect(existsSync(path.join(tmpDir, ".agents", "skills", "cite-research", "SKILL.md"))).toBe(true)
  expect(existsSync(path.join(tmpDir, ".agents", "skills", "shutong-research", "SKILL.md"))).toBe(true)
  expect(JSON.parse(readFileSync(path.join(tmpDir, "opencode.json"), "utf8")).mcp.shutong).toBeDefined()
  const agents = readFileSync(path.join(tmpDir, "AGENTS.md"), "utf8")
  expect(agents).toContain("<!-- SHUTONG:BEGIN")
  expect(agents).toContain("<!-- SHUTONG:CORPUS:BEGIN -->")
  expect(result.written.length).toBeGreaterThan(0)
  rmSync(tmpDir, { recursive: true, force: true })
})

test("initProject updates an existing OpenCode JSONC config", () => {
  mkdirSync(tmpDir, { recursive: true })
  writeFileSync(path.join(tmpDir, "opencode.jsonc"), "// OpenCode\n{\n  \"theme\": \"dark\"\n}\n")
  initProject(tmpDir, false, "opencode")
  expect(existsSync(path.join(tmpDir, "opencode.json"))).toBe(false)
  const config = Bun.JSONC.parse(readFileSync(path.join(tmpDir, "opencode.jsonc"), "utf8")) as any
  expect(config.mcp.shutong).toBeDefined()
  rmSync(tmpDir, { recursive: true, force: true })
})

test("initProject uses the configured Python executable for MCP", () => {
  mkdirSync(path.join(tmpDir, ".opencode"), { recursive: true })
  mkdirSync(path.join(tmpDir, ".shutong"), { recursive: true })
  writeFileSync(path.join(tmpDir, ".shutong", "config.toml"), "[backend]\npython = \"/opt/shutong/bin/python\"\n")
  initProject(tmpDir, false, "opencode")
  expect(JSON.parse(readFileSync(path.join(tmpDir, "opencode.json"), "utf8")).mcp.shutong.command[0]).toBe("/opt/shutong/bin/python")
  rmSync(tmpDir, { recursive: true, force: true })
})

test("initProject creates all five host integrations", () => {
  const hosts = [
    ["opencode", ".agents/skills/corpus-status/SKILL.md"],
    ["claude", ".claude/commands/research.md"],
    ["codex", ".codex/config.toml"],
    ["pi", ".pi/skills/corpus-status/SKILL.md"],
    ["hermes", ".hermes/SHUTONG-MCP.md"],
  ] as const
  for (const [host, artifact] of hosts) {
    const root = path.join(tmpDir, host)
    initProject(root, false, host)
    expect(existsSync(path.join(root, artifact))).toBe(true)
    expect(existsSync(path.join(root, host === "pi" ? ".pi/skills/paper-workspace/SKILL.md" : host === "codex" ? ".codex/skills/paper-workspace/SKILL.md" : ".agents/skills/paper-workspace/SKILL.md"))).toBe(true)
    expect(existsSync(path.join(root, host === "pi" ? ".pi/skills/shutong-research/SKILL.md" : host === "codex" ? ".codex/skills/shutong-research/SKILL.md" : ".agents/skills/shutong-research/SKILL.md"))).toBe(true)
    // No host receives agent definitions; the surface is MCP plus skills.
    if (host === "codex") expect(existsSync(path.join(root, ".codex", "agents"))).toBe(false)
    if (host === "opencode") expect(existsSync(path.join(root, ".opencode", "agents"))).toBe(false)
    if (host === "claude") expect(existsSync(path.join(root, ".claude", "agents"))).toBe(false)
    if (host === "opencode") expect(JSON.parse(readFileSync(path.join(root, "opencode.json"), "utf8")).default_agent).toBeUndefined()
    if (host === "claude") expect(existsSync(path.join(root, "CLAUDE.md"))).toBe(true)
    const skill = readFileSync(path.join(root, host === "pi" ? ".pi/skills/shutong-research/SKILL.md" : host === "codex" ? ".codex/skills/shutong-research/SKILL.md" : ".agents/skills/shutong-research/SKILL.md"), "utf8")
    expect(skill).not.toContain("shutong_translate")
    expect(skill).not.toContain("shutong_paper_set_bibliography")
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
