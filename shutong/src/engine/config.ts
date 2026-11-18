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

function inferDefaultPythonBin(): string {
  const localVenv = path.resolve(import.meta.dir, "../../../packages/shutong-backend/.venv/bin/python")
  return existsSync(localVenv) ? localVenv : DEFAULT_PYTHON_BIN
}

const defaultLlm: LlmConfig = {
  provider: "ollama",
  model: DEFAULT_LLM_MODEL,
  temperature: DEFAULT_TEMPERATURE,
  max_tokens: DEFAULT_MAX_TOKENS,
}

const defaultPlugins: PluginsConfig = {
  directory: "plugins",
  enabled: [],
}

const defaultMemory: MemoryConfig = {
  backend: DEFAULT_MEMORY_BACKEND,
  postgresql_url: undefined,
}

const defaultConfig: ShutongConfig = {
  corpus_root: DEFAULT_CORPUS_ROOT,
  library_root: DEFAULT_LIBRARY_ROOT,
  glossary_dir: ".shutong/glossary",
  python_bin: inferDefaultPythonBin(),
  backend_module: DEFAULT_BACKEND_MODULE,
  llm: defaultLlm,
  plugins: defaultPlugins,
  memory: defaultMemory,
}

function parseConfigToml(parsed: any): ShutongConfig {
  return {
    corpus_root: parsed.project?.corpus_root ?? parsed.corpus_root ?? DEFAULT_CORPUS_ROOT,
    library_root: parsed.project?.library_root ?? parsed.library_root ?? DEFAULT_LIBRARY_ROOT,
    glossary_dir: parsed.scholar?.glossary_dir ?? parsed.glossary_dir ?? ".shutong/glossary",
    python_bin: parsed.backend?.python ?? parsed.python_bin ?? DEFAULT_PYTHON_BIN,
    backend_module: parsed.backend?.module ?? parsed.backend_module ?? DEFAULT_BACKEND_MODULE,
    llm: {
      provider: (parsed.model?.provider ?? parsed.llm?.provider ?? "ollama") as LlmConfig["provider"],
      model: parsed.model?.name ?? parsed.llm?.model ?? DEFAULT_LLM_MODEL,
      temperature: parsed.model?.temperature ?? parsed.llm?.temperature ?? DEFAULT_TEMPERATURE,
      max_tokens: parsed.model?.max_tokens ?? parsed.llm?.max_tokens ?? DEFAULT_MAX_TOKENS,
      apiKey: parsed.model?.api_key ?? parsed.llm?.apiKey ?? undefined,
      baseURL: parsed.model?.base_url ?? parsed.llm?.baseURL ?? undefined,
    },
    plugins: { ...defaultPlugins, ...(parsed.plugins ?? {}) },
    memory: { ...defaultMemory, ...(parsed.memory ?? {}) },
  }
}

function serializeConfig(config: ShutongConfig): string {
  return smolToml.stringify({
    project: {
      corpus_root: config.corpus_root,
      library_root: config.library_root,
    },
    backend: {
      python: config.python_bin,
      module: config.backend_module,
    },
    model: {
      provider: config.llm.provider,
      name: config.llm.model,
      temperature: config.llm.temperature,
      max_tokens: config.llm.max_tokens,
      ...(config.llm.apiKey ? { api_key: config.llm.apiKey } : {}),
      ...(config.llm.baseURL ? { base_url: config.llm.baseURL } : {}),
    },
    permissions: {
      read: "allow",
      edit: "ask",
      bash: "ask",
      network: "ask",
    },
    scholar: {
      glossary_dir: config.glossary_dir,
    },
  } as any)
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
  if (!existsSync(configPath)) return { ...defaultConfig }

  const content = readFileSync(configPath, "utf-8")
  try {
    return parseConfigToml(smolToml.parse(content) as any)
  } catch {
    return { ...defaultConfig }
  }
}

export function discoverConfig(root = process.cwd()): ShutongConfig {
  const projectPath = projectConfigPath(root)
  const userPath = userConfigPath()
  const projectConfig = existsSync(projectPath)
    ? resolveConfigPaths(loadConfig(projectPath), projectPath)
    : { ...defaultConfig }
  const userConfig = existsSync(userPath)
    ? resolveConfigPaths(loadConfig(userPath), userPath)
    : { ...defaultConfig }

  return {
    ...userConfig,
    ...projectConfig,
    llm: { ...userConfig.llm, ...projectConfig.llm },
    plugins: { ...userConfig.plugins, ...projectConfig.plugins },
    memory: { ...userConfig.memory, ...projectConfig.memory },
  }
}

export function hasUserConfig(): boolean {
  return existsSync(userConfigPath())
}

export function hasProjectConfig(root = process.cwd()): boolean {
  return existsSync(projectConfigPath(root))
}

export function writeUserConfig(patch: Partial<ShutongConfig>): void {
  mkdirSync(userConfigDir(), { recursive: true })
  const existing = hasUserConfig() ? loadConfig(userConfigPath()) : { ...defaultConfig }
  const merged: ShutongConfig = {
    ...existing,
    ...patch,
    llm: { ...existing.llm, ...(patch.llm ?? {}) },
    plugins: { ...existing.plugins, ...(patch.plugins ?? {}) },
    memory: { ...existing.memory, ...(patch.memory ?? {}) },
  }
  writeFileSync(userConfigPath(), serializeConfig(merged))
}

export function writeProjectConfig(patch: Partial<ShutongConfig>, root = process.cwd()): void {
  mkdirSync(projectConfigDir(root), { recursive: true })
  const configPath = projectConfigPath(root)
  const existing = existsSync(configPath) ? loadConfig(configPath) : { ...defaultConfig }
  const merged: ShutongConfig = {
    ...existing,
    ...patch,
    llm: { ...existing.llm, ...(patch.llm ?? {}) },
    plugins: { ...existing.plugins, ...(patch.plugins ?? {}) },
    memory: { ...existing.memory, ...(patch.memory ?? {}) },
  }
  writeFileSync(configPath, serializeConfig(merged))
}
