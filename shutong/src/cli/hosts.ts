import { existsSync } from "fs"
import path from "path"

export const HOSTS = ["opencode", "claude", "codex", "pi", "omp", "hermes"] as const
export type Host = typeof HOSTS[number]

const markers: Record<Host, string[]> = {
  opencode: [".opencode", "opencode.json", "opencode.jsonc"],
  claude: [".claude", "CLAUDE.md", ".mcp.json"],
  codex: [".codex"],
  pi: [".pi"],
  omp: [".omp"],
  hermes: [".hermes.md"],
}

export function detectHosts(root: string): Host[] {
  return HOSTS.filter((host) => markers[host].some((marker) => existsSync(path.join(root, marker))))
}
