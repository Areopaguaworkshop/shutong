import { test, expect } from "bun:test"
import { loadConfig, discoverConfig, hasProjectConfig, projectConfigPath, resolveConfigPaths, userConfigPath, writeProjectConfig, writeUserConfig } from "../src/engine/config"
import { mkdirSync, rmSync, existsSync, writeFileSync } from "fs"
import path from "path"
import os from "os"

const tmpDir = path.join(os.tmpdir(), "shutong-config-test")

test("loadConfig returns defaults for missing file", () => {
  const config = loadConfig(path.join(tmpDir, "nonexistent.toml"))
  expect(config.corpus_root).toBe("corpus")
  expect(config.library_root).toBe("library")
  expect(config.llm.model).toBe("glm-5.3-flash:cloud")
})

test("projectConfigPath returns .shutong/config.toml", () => {
  const p = projectConfigPath("/tmp/test-project")
  expect(p).toContain(".shutong")
  expect(p).toContain("config.toml")
})

test("writeProjectConfig creates config file", () => {
  const testRoot = path.join(tmpDir, "project-test")
  mkdirSync(testRoot, { recursive: true })
  writeProjectConfig({ corpus_root: "my-corpus" }, testRoot)
  const configPath = projectConfigPath(testRoot)
  expect(existsSync(configPath)).toBe(true)
  
  const loaded = loadConfig(configPath)
  expect(loaded.corpus_root).toBe("my-corpus")
  
  rmSync(testRoot, { recursive: true, force: true })
})

test("default config has correct backend module", () => {
  const config = loadConfig(path.join(tmpDir, "nonexistent.toml"))
  expect(config.backend_module).toBe("shutong_backend.rpc_server")
})

test("default config has Ollama provider settings", () => {
  const config = loadConfig(path.join(tmpDir, "nonexistent.toml"))
  expect(config.llm.model).toContain("glm")
  expect(config.llm.temperature).toBe(0.1)
})

test("project config paths resolve from the project root", () => {
  const configPath = path.join(tmpDir, "research", ".shutong", "config.toml")
  mkdirSync(path.dirname(configPath), { recursive: true })
  writeFileSync(configPath, "[project]\ncorpus_root = \"../corpus\"\nlibrary_root = \"../library\"\n[backend]\npython = \"../../.venv/bin/python\"\n[scholar]\nglossary_dir = \"glossary\"\n")
  const config = resolveConfigPaths(loadConfig(configPath), configPath)
  expect(config.corpus_root).toBe(path.join(tmpDir, "corpus"))
  expect(config.library_root).toBe(path.join(tmpDir, "library"))
  expect(config.glossary_dir).toBe(path.join(tmpDir, "research", "glossary"))
  expect(config.python_bin).toBe(path.join("/tmp", ".venv", "bin", "python"))
})

test("discoverConfig resolves a project's configured corpus path", () => {
  const root = path.join(tmpDir, "discovery-project")
  const configPath = projectConfigPath(root)
  mkdirSync(path.dirname(configPath), { recursive: true })
  writeFileSync(configPath, "[project]\ncorpus_root = \"../corpus\"\nlibrary_root = \"../library\"\n")
  const config = discoverConfig(root)
  expect(config.corpus_root).toBe(path.join(tmpDir, "corpus"))
  expect(config.library_root).toBe(path.join(tmpDir, "library"))
  rmSync(root, { recursive: true, force: true })
})
