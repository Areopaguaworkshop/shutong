import { existsSync, mkdirSync } from "fs"
import path from "path"
import { setupDataRoot, setupVenvPython, writeUserConfig } from "../engine/config"

function run(command: string[]) {
  const result = Bun.spawnSync(command, { stdout: "pipe", stderr: "pipe" })
  return { ok: result.exitCode === 0, detail: new TextDecoder().decode(result.stdout || result.stderr).trim() }
}

/** Create one local backend environment shared by all Shutong projects. */
export function setupBackend() {
  const python = Bun.which("python3")
  if (!python) return { ok: false, detail: "Python 3.12+ is required. Install Python, then run shutong setup again." }
  const version = run([python, "--version"])
  const match = /Python (\d+)\.(\d+)/.exec(version.detail)
  if (!version.ok || !match || Number(match[1]) !== 3 || Number(match[2]) < 12) return { ok: false, detail: "Python 3.12+ is required. Install it, then run shutong setup again." }
  const backend = [
    path.resolve(import.meta.dir, "../../python-backend"),
    path.resolve(import.meta.dir, "../../../packages/shutong-backend"),
  ].find((candidate) => existsSync(path.join(candidate, "pyproject.toml")))
  if (!backend) return { ok: false, detail: "Bundled Shutong backend is unavailable; reinstall the npm package before initializing a host." }
  const venvPython = setupVenvPython()
  if (!existsSync(venvPython)) {
    mkdirSync(setupDataRoot(), { recursive: true })
    const created = run([python, "-m", "venv", path.join(setupDataRoot(), "venv")])
    if (!created.ok) return { ok: false, detail: created.detail }
  }
  const installed = run([venvPython, "-m", "pip", "install", "--disable-pip-version-check", backend])
  if (!installed.ok) return { ok: false, detail: installed.detail }
  const checked = run([venvPython, "-c", "import shutong_backend"])
  if (!checked.ok) return { ok: false, detail: checked.detail }
  // Persist the interpreter so `shutong init` and the engine reuse the same environment.
  writeUserConfig({ python_bin: venvPython })
  return { ok: true, python: venvPython, detail: "Backend ready." }
}
