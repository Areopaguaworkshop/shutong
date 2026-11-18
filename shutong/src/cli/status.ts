import { discoverConfig, hasProjectConfig, loadConfig, projectConfigPath, resolveConfigPaths, userConfigPath } from "../engine/config"

export function runStatus(root = process.cwd(), configPath?: string): void {
  const config = configPath ? resolveConfigPaths(loadConfig(configPath), configPath) : discoverConfig()

  const projectConfig = configPath ?? (hasProjectConfig(root) ? projectConfigPath(root) : "(not initialized)")
  const userConfig = hasProjectConfig(root) ? userConfigPath() : "(defaults)"

  console.log("shutong 0.4.0")
  console.log(`project:     ${projectConfig}`)
  console.log(`global:      ${userConfig}`)
  console.log(`corpus_root: ${config.corpus_root}`)
  console.log(`library:     ${config.library_root}`)
  console.log(`python_bin:  ${config.python_bin}`)
  console.log(`backend:     ${config.backend_module}`)
  console.log(`llm.model:   ${config.llm.model}`)
}
