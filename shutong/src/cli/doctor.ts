import { existsSync } from "fs"
import path from "path"
import { discoverConfig, hasProjectConfig, projectConfigPath, userConfigPath } from "../engine/config"
import { BackendClient } from "../engine/backend-client"

async function checkOllama(model: string): Promise<{ ok: boolean; detail: string }> {
  try {
    const response = await fetch("http://localhost:11434/api/tags")
    if (!response.ok) {
      return { ok: false, detail: `HTTP ${response.status}` }
    }
    const payload = await response.json() as { models?: Array<{ name?: string }> }
    const names = (payload.models ?? []).map((item) => item.name ?? "")
    const found = names.find((item) => item.includes(model))
    return { ok: Boolean(found), detail: found ?? `Model ${model} not pulled` }
  } catch (error: any) {
    return { ok: false, detail: error.message }
  }
}

export async function runDoctor(root = process.cwd()): Promise<number> {
  const config = discoverConfig(root)
  const checks: Array<{ name: string; ok: boolean; detail: string }> = []

  checks.push({
    name: "Project config",
    ok: hasProjectConfig(root),
    detail: hasProjectConfig(root) ? projectConfigPath(root) : "Missing .shutong/config.toml",
  })
  checks.push({
    name: "Global config",
    ok: true,
    detail: existsSync(userConfigPath()) ? userConfigPath() : "Optional global config not found",
  })
  checks.push({
    name: "Corpus directory",
    ok: existsSync(config.corpus_root),
    detail: config.corpus_root,
  })
  checks.push({
    name: "Library directory",
    ok: existsSync(config.library_root),
    detail: config.library_root,
  })

  const ollama = await checkOllama(config.llm.model)
  checks.push({ name: "Ollama model", ok: ollama.ok, detail: ollama.detail })

  const backend = new BackendClient(
    config.python_bin,
    config.backend_module,
    path.join(config.corpus_root, ".shutong"),
    config.llm.model,
    undefined,
    config.glossary_dir,
    config.library_root,
  )
  try {
    const health = await backend.health()
    checks.push({
      name: "Backend health",
      ok: health?.status === "ok",
      detail: `${health?.backend ?? "unknown"} v${health?.version ?? "?"} (${health?.tool_count ?? 0} tools)`,
    })
  } catch (error: any) {
    checks.push({ name: "Backend health", ok: false, detail: error.message })
  } finally {
    await backend.shutdown()
  }

  let failures = 0
  for (const check of checks) {
    const status = check.ok ? "OK" : "FAIL"
    console.log(`[${status}] ${check.name}: ${check.detail}`)
    if (!check.ok) failures += 1
  }
  return failures
}
