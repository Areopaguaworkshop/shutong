import { test, expect } from "bun:test"
import { SessionStore } from "../src/engine/session-store"
import { mkdirSync, rmSync } from "fs"
import path from "path"
import os from "os"
import type { ChatMessage } from "../src/shared/types"

const tmpDir = path.join(os.tmpdir(), "shutong-session-test")

test("SessionStore creates and loads sessions", () => {
  mkdirSync(tmpDir, { recursive: true })
  const store = new SessionStore(tmpDir)
  const id = store.createId()

  const messages: ChatMessage[] = [
    { role: "user", content: "hello", citations: [], timestamp: Date.now() },
    { role: "assistant", content: "hi there", citations: [], timestamp: Date.now() },
  ]

  store.save(id, messages)
  const loaded = store.load(id)
  expect(loaded.length).toBe(2)
  expect(loaded[0].content).toBe("hello")
  expect(loaded[1].content).toBe("hi there")

  rmSync(tmpDir, { recursive: true, force: true })
})

test("SessionStore list returns sessions", () => {
  mkdirSync(tmpDir, { recursive: true })
  const store = new SessionStore(tmpDir)
  const id1 = store.createId()
  const id2 = store.createId()

  store.save(id1, [{ role: "user", content: "first", citations: [] }])
  store.save(id2, [{ role: "user", content: "second", citations: [] }])

  const sessions = store.list()
  expect(sessions.length).toBe(2)

  rmSync(tmpDir, { recursive: true, force: true })
})

test("SessionStore updates existing session", () => {
  mkdirSync(tmpDir, { recursive: true })
  const store = new SessionStore(tmpDir)
  const id = store.createId()

  store.save(id, [{ role: "user", content: "first", citations: [] }])
  store.save(id, [
    { role: "user", content: "first", citations: [] },
    { role: "assistant", content: "reply", citations: [] },
  ])

  const loaded = store.load(id)
  expect(loaded.length).toBe(2)

  const meta = store.loadMeta(id)!
  expect(meta.messageCount).toBe(2)

  rmSync(tmpDir, { recursive: true, force: true })
})

test("SessionStore auto-generates title from first user message", () => {
  mkdirSync(tmpDir, { recursive: true })
  const store = new SessionStore(tmpDir)
  const id = store.createId()

  store.save(id, [{ role: "user", content: "What does Athanasius say about the Logos?", citations: [] }])

  const meta = store.loadMeta(id)!
  expect(meta.title).toContain("Athanasius")

  rmSync(tmpDir, { recursive: true, force: true })
})

test("SessionStore delete removes session", () => {
  mkdirSync(tmpDir, { recursive: true })
  const store = new SessionStore(tmpDir)
  const id = store.createId()

  store.save(id, [{ role: "user", content: "test", citations: [] }])
  expect(store.list().length).toBe(1)

  store.delete(id)
  expect(store.list().length).toBe(0)
  expect(store.load(id)).toEqual([])

  rmSync(tmpDir, { recursive: true, force: true })
})
