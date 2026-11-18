import { readFileSync, writeFileSync, mkdirSync, existsSync } from "fs"
import path from "path"
import * as smolToml from "smol-toml"
import type { ShutongConfig, LlmConfig, PluginsConfig, MemoryConfig } from "../shared/types"
import {
  DEFAULT_BACKEND_MODULE,
  DEFAULT_CORPUS_ROOT,
  DEFAULT_LIBRARY_ROOT,
  DEFAULT_PYTHON_BIN,
  DEFAULT_LLM_MODEL,
  DEFAULT_TEMPERATURE,
  DEFAULT_MAX_TOKENS,
  DEFAULT_MEMORY_BACKEND,
} from "../shared/constants"

/** Root of the per-user Shutong data directory (the setup venv lives here). */
export function setupDataRoot(): string {
  return path.join(process.env.XDG_DATA_HOME ?? path.join(process.env.HOME ?? "/tmp", ".local", "share"), "shutong")
}

/** Python interpreter created by `shutong setup`, whether or not it exists yet. */
export function setupVenvPython(): string {
  return path.join(setupDataRoot(), "venv", "bin", "python")
}

function inferDefaultPythonBin(): string {
  const setupVenv = setupVenvPython()
  if (existsSync(setupVenv)) return setupVenv
  const localVenv = path.resolve(import.meta.dir, "../../../packages/shutong-backend/.venv/bin/python")
  if (existsSync(localVenv)) return localVenv
  return DEFAULT_PYTHON_BIN
}

function createDefaultConfig(): ShutongConfig {
  return {
    corpus_root: DEFAULT_CORPUS_ROOT,
    library_root: DEFAULT_LIBRARY_ROOT,
    glossary_dir: ".shutong/glossary",
    python_bin: inferDefaultPythonBin(),
    backend_module: DEFAULT_BACKEND_MODULE,
    llm: {
      provider: "ollama",
      model: DEFAULT_LLM_MODEL,
      temperature: DEFAULT_TEMPERATURE,
      max_tokens: DEFAULT_MAX_TOKENS,
    },
    plugins: { directory: "plugins", enabled: [] },
    memory: { backend: DEFAULT_MEMORY_BACKEND, postgresql_url: undefined },
  }
}

/** Only the keys actually present in a TOML file, so defaults never shadow explicit config. */
function parseExplicitConfigToml(parsed: any): Partial<ShutongConfig> {
  const config: Partial<ShutongConfig> = {}
  if (parsed.project?.corpus_root !== undefined || parsed.corpus_root !== undefined) config.corpus_root = parsed.project?.corpus_root ?? parsed.corpus_root
  if (parsed.project?.library_root !== undefined || parsed.library_root !== undefined) config.library_root = parsed.project?.library_root ?? parsed.library_root
  if (parsed.scholar?.glossary_dir !== undefined || parsed.glossary_dir !== undefined) config.glossary_dir = parsed.scholar?.glossary_dir ?? parsed.glossary_dir
  if (parsed.backend?.python !== undefined || parsed.python_bin !== undefined) config.python_bin = parsed.backend?.python ?? parsed.python_bin
  if (parsed.backend?.module !== undefined || parsed.backend_module !== undefined) config.backend_module = parsed.backend?.module ?? parsed.backend_module

  const llm: Partial<LlmConfig> = {}
  const provider = parsed.model?.provider ?? parsed.llm?.provider
  const model = parsed.model?.name ?? parsed.llm?.model
  const temperature = parsed.model?.temperature ?? parsed.llm?.temperature
  const maxTokens = parsed.model?.max_tokens ?? parsed.llm?.max_tokens
  const apiKey = parsed.model?.api_key ?? parsed.llm?.apiKey
  const baseURL = parsed.model?.base_url ?? parsed.llm?.baseURL
  if (provider !== undefined) llm.provider = provider
  if (model !== undefined) llm.model = model
  if (temperature !== undefined) llm.temperature = temperature
  if (maxTokens !== undefined) llm.max_tokens = maxTokens
  if (apiKey !== undefined) llm.apiKey = apiKey
  if (baseURL !== undefined) llm.baseURL = baseURL
  if (Object.keys(llm).length > 0) config.llm = llm as LlmConfig
  if (parsed.plugins !== undefined) config.plugins = parsed.plugins as PluginsConfig
  if (parsed.memory !== undefined) config.memory = parsed.memory as MemoryConfig
  return config
}

function mergeConfig(base: ShutongConfig, explicit: Partial<ShutongConfig>): ShutongConfig {
  return {
    ...base,
    ...explicit,
    llm: { ...base.llm, ...(explicit.llm ?? {}) },
    plugins: { ...base.plugins, ...(explicit.plugins ?? {}) },
    memory: { ...base.memory, ...(explicit.memory ?? {}) },
  }
}

function readExplicitConfig(configPath: string): Partial<ShutongConfig> {
  try {
    return parseExplicitConfigToml(smolToml.parse(readFileSync(configPath, "utf-8")) as any)
  } catch {
    return {}
  }
}

function serializeConfig(config: Partial<ShutongConfig>): string {
  const output: Record<string, any> = {}
  const project: Record<string, string> = {}
  if (config.corpus_root !== undefined) project.corpus_root = config.corpus_root
  if (config.library_root !== undefined) project.library_root = config.library_root
  if (Object.keys(project).length > 0) output.project = project

  const backend: Record<string, string> = {}
  if (config.python_bin !== undefined) backend.python = config.python_bin
  if (config.backend_module !== undefined) backend.module = config.backend_module
  if (Object.keys(backend).length > 0) output.backend = backend

  const model: Record<string, unknown> = {}
  if (config.llm?.provider !== undefined) model.provider = config.llm.provider
  if (config.llm?.model !== undefined) model.name = config.llm.model
  if (config.llm?.temperature !== undefined) model.temperature = config.llm.temperature
  if (config.llm?.max_tokens !== undefined) model.max_tokens = config.llm.max_tokens
  if (config.llm?.apiKey !== undefined) model.api_key = config.llm.apiKey
  if (config.llm?.baseURL !== undefined) model.base_url = config.llm.baseURL
  if (Object.keys(model).length > 0) output.model = model

  output.permissions = { read: "allow", edit: "ask", bash: "ask", network: "ask" }

  if (config.glossary_dir !== undefined) output.scholar = { glossary_dir: config.glossary_dir }
  if (config.plugins !== undefined) output.plugins = config.plugins
  if (config.memory !== undefined) output.memory = config.memory
  return smolToml.stringify(output as any)
}

/** Resolve project paths against the project root and user paths against their config directory. */
export function resolveConfigPaths(config: ShutongConfig, configPath: string): ShutongConfig {
  const configDir = path.dirname(path.resolve(configPath))
  const root = path.basename(configDir) === ".shutong" ? path.dirname(configDir) : configDir
  const pythonBin = config.python_bin.includes(path.sep)
    ? path.resolve(root, config.python_bin)
    : config.python_bin
  return {
    ...config,
    corpus_root: path.resolve(root, config.corpus_root),
    library_root: path.resolve(root, config.library_root),
    glossary_dir: path.resolve(root, config.glossary_dir),
    python_bin: pythonBin,
  }
}

export function userConfigDir(): string {
  return path.join(
    process.env.XDG_CONFIG_HOME ?? path.join(process.env.HOME ?? "/tmp", ".config"),
    "shutong",
  )
}

export function userConfigPath(): string {
  return path.join(userConfigDir(), "config.toml")
}

export function projectConfigDir(root = process.cwd()): string {
  return path.join(root, ".shutong")
}

export function projectConfigPath(root = process.cwd()): string {
  return path.join(projectConfigDir(root), "config.toml")
}

export function loadConfig(configPath: string): ShutongConfig {
  const defaults = createDefaultConfig()
  if (!existsSync(configPath)) return defaults
  return mergeConfig(defaults, readExplicitConfig(configPath))
}

export function discoverConfig(root = process.cwd()): ShutongConfig {
  let config = createDefaultConfig()
  const userPath = userConfigPath()
  if (existsSync(userPath)) {
    const explicit = readExplicitConfig(userPath)
    const resolved = resolveConfigPaths(mergeConfig(config, explicit), userPath)
    config = overlayExplicit(config, explicit, resolved)
  }
  const projectPath = projectConfigPath(root)
  if (existsSync(projectPath)) {
    const explicit = readExplicitConfig(projectPath)
    const resolved = resolveConfigPaths(mergeConfig(config, explicit), projectPath)
    config = overlayExplicit(config, explicit, resolved)
  }
  return config
}

/** Apply only the fields a config file actually sets; absent fields keep the previous layer. */
function overlayExplicit(base: ShutongConfig, explicit: Partial<ShutongConfig>, resolved: ShutongConfig): ShutongConfig {
  const next: ShutongConfig = {
    ...base,
    llm: { ...base.llm },
    plugins: { ...base.plugins },
    memory: { ...base.memory },
  }
  for (const key of ["corpus_root", "library_root", "glossary_dir", "python_bin", "backend_module"] as const) {
    if (explicit[key] !== undefined) next[key] = resolved[key]
  }
  next.llm = { ...base.llm, ...(explicit.llm ?? {}) }
  next.plugins = { ...base.plugins, ...(explicit.plugins ?? {}) }
  next.memory = { ...base.memory, ...(explicit.memory ?? {}) }
  return next
}

export function hasUserConfig(): boolean {
  return existsSync(userConfigPath())
}

export function hasProjectConfig(root = process.cwd()): boolean {
  return existsSync(projectConfigPath(root))
}

function mergePartial(existing: Partial<ShutongConfig>, patch: Partial<ShutongConfig>): Partial<ShutongConfig> {
  const merged: Partial<ShutongConfig> = { ...existing, ...patch }
  const llm = { ...(existing.llm ?? {}), ...(patch.llm ?? {}) }
  if (Object.keys(llm).length > 0) merged.llm = llm as LlmConfig
  const plugins = { ...(existing.plugins ?? {}), ...(patch.plugins ?? {}) }
  if (Object.keys(plugins).length > 0) merged.plugins = plugins as PluginsConfig
  const memory = { ...(existing.memory ?? {}), ...(patch.memory ?? {}) }
  if (Object.keys(memory).length > 0) merged.memory = memory as MemoryConfig
  return merged
}

export function writeUserConfig(patch: Partial<ShutongConfig>): void {
  mkdirSync(userConfigDir(), { recursive: true })
  const existing = hasUserConfig() ? readExplicitConfig(userConfigPath()) : {}
  writeFileSync(userConfigPath(), serializeConfig(mergePartial(existing, patch)))
}

export function writeProjectConfig(patch: Partial<ShutongConfig>, root = process.cwd()): void {
  mkdirSync(projectConfigDir(root), { recursive: true })
  const configPath = projectConfigPath(root)
  const existing = existsSync(configPath) ? readExplicitConfig(configPath) : {}
  // Project scaffolds must not persist inferred defaults; only explicit project fields are written.
  writeFileSync(configPath, serializeConfig(mergePartial(existing, patch)))
}
