import { test, expect } from "bun:test"
import { mkdirSync, rmSync } from "fs"
import os from "os"
import path from "path"
import { detectHosts } from "../src/cli/hosts"

test("detectHosts finds project markers", () => {
  const root = path.join(os.tmpdir(), "shutong-hosts-test")
  mkdirSync(path.join(root, ".opencode"), { recursive: true })
  mkdirSync(path.join(root, ".codex"), { recursive: true })
  expect(detectHosts(root)).toEqual(["opencode", "codex"])
  rmSync(root, { recursive: true, force: true })
})
