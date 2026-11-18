import { expect, test } from "bun:test"
import { mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "fs"
import os from "os"
import path from "path"

test("package ships runtime files without project data, stale files or symlinks", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "shutong-package-test-"))
  const launcher = path.join(root, "shutong")
  const backend = "packages/shutong-backend/"
  const write = (name: string, text = "private fixture") => {
    const file = path.join(root, name)
    mkdirSync(path.dirname(file), { recursive: true })
    writeFileSync(file, text)
  }
  try {
    const manifest = JSON.parse(readFileSync(path.join(import.meta.dir, "../package.json"), "utf8"))
    // This fixture checks file boundaries without needing a dependency lockfile.
    delete manifest.dependencies
    delete manifest.devDependencies
    write("shutong/package.json", JSON.stringify(manifest))
    write("shutong/scripts/bundle-backend.ts", readFileSync(path.join(import.meta.dir, "../scripts/bundle-backend.ts"), "utf8"))
    write("shutong/bin/shutong", "#!/usr/bin/env bun\n")
    write("shutong/src/index.ts", "export {}\n")
    write(backend + "pyproject.toml", "[project]\nname = 'shutong-backend'\n")
    write(backend + "shutong_backend/__init__.py", "")
    write(backend + "shutong_backend/agents/run.py", "")
    write(backend + "shutong_backend/templates/AGENTS.md.j2", "{{ snapshot }}")
    write(backend + "shutong_backend/templates/glossary/theology-en-zh.json", "{}")
    write(backend + "shutong_backend/templates/agents/noter.md", "Generic agent")
    for (const name of [".omc/state/replay.jsonl", ".shutong/config.toml", "corpus/source.json", "library/paper.pdf", "papers/draft.md", "projects/private.json", "dist/shutong", "shutong-err.log", ".env"]) {
      write("shutong/" + name)
      write(backend + name)
    }
    for (const name of ["__pycache__/private.pyc", ".memory/private.py", "notes.json", "debug.log", "templates/.private/notes.md", "templates/source.pdf"]) write(backend + "shutong_backend/" + name)
    write("shutong/python-backend/shutong_backend/stale.py")
    symlinkSync(path.join(root, backend, "papers/draft.md"), path.join(root, backend, "shutong_backend/leak.py"))
    const bundled = Bun.spawnSync([process.execPath, "scripts/bundle-backend.ts"], { cwd: launcher })
    expect(bundled.exitCode).toBe(0)
    const archive = path.join(root, "release.tgz")
    const packed = Bun.spawnSync([process.execPath, "pm", "pack", "--ignore-scripts", "--filename", archive], { cwd: launcher, stdout: "pipe", stderr: "pipe" })
    expect(packed.exitCode).toBe(0)
    const listing = Bun.spawnSync(["tar", "-tzf", archive], { stdout: "pipe", stderr: "pipe" })
    expect(listing.exitCode).toBe(0)
    const files = listing.stdout.toString().trim().split("\n").map((file) => file.replace(/^package\//, "")).sort()
    expect(files).toEqual([
      "bin/shutong", "package.json", "src/index.ts",
      "python-backend/pyproject.toml",
      "python-backend/shutong_backend/__init__.py",
      "python-backend/shutong_backend/agents/run.py",
      "python-backend/shutong_backend/templates/AGENTS.md.j2",
      "python-backend/shutong_backend/templates/agents/noter.md",
      "python-backend/shutong_backend/templates/glossary/theology-en-zh.json",
    ].sort())
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})
