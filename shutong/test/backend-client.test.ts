import { test, expect } from "bun:test"
import { BackendClient } from "../src/engine/backend-client"
import { resolveToolCall, getTool, allTools } from "../src/engine/tool-registry"

test("tool registry resolves known tools", () => {
  const search = getTool("shutong_search")
  expect(search).toBeDefined()
  expect(search!.method).toBe("tool_call")

  const ingest = getTool("shutong_ingest")
  expect(ingest).toBeDefined()
  expect(ingest!.method).toBe("tool_call")

  const unknown = getTool("nonexistent")
  expect(unknown).toBeUndefined()
})

test("resolveToolCall maps tool names to backend methods", () => {
  const resolved = resolveToolCall("shutong_search", { query: "test", top_k: 10 })
  expect(resolved.method).toBe("tool_call")
  expect(resolved.params).toEqual({ name: "shutong_search", arguments: { query: "test", top_k: 10 } })

  const ingestResolved = resolveToolCall("shutong_ingest", { source: "/path/to/file.pdf" })
  expect(ingestResolved.method).toBe("tool_call")
  expect(ingestResolved.params).toEqual({ name: "shutong_ingest", arguments: { source: "/path/to/file.pdf" } })
})

test("resolveToolCall throws for unknown tools", () => {
  expect(() => resolveToolCall("unknown_tool", {})).toThrow("Unknown tool")
})

test("allTools returns expected count", () => {
  const tools = allTools()
  expect(tools.length).toBe(26)
  const names = tools.map(t => t.name)
  expect(names).toContain("shutong_search")
  expect(names).toContain("shutong_analysis")
  expect(names).toContain("shutong_workspace")
  expect(names).toContain("shutong_ingest")
  expect(names).toContain("shutong_verify")
  expect(names).not.toContain("shutong_translate")
  expect(names).not.toContain("shutong_glossary_lookup")
})

test("BackendClient methods exist and are callable", () => {
  const client = new BackendClient("python3", "shutong_backend.rpc_server", "/tmp/test", "test-model")
  expect(typeof client.health).toBe("function")
  expect(typeof client.search).toBe("function")
  expect(typeof client.chatContext).toBe("function")
  expect(typeof client.ingest).toBe("function")
  expect(typeof client.ingestStatus).toBe("function")
  expect(typeof client.verifyDocument).toBe("function")
  expect(typeof client.verifyAll).toBe("function")
  expect(typeof client.resolveCitation).toBe("function")
  expect(typeof client.translate).toBe("function")
  expect(typeof client.renderBilingual).toBe("function")
  expect(typeof client.glossaryLookup).toBe("function")
  expect(typeof client.glossaryAdd).toBe("function")
  expect(typeof client.glossaryList).toBe("function")
  expect(typeof client.memorySearch).toBe("function")
  expect(typeof client.memorySave).toBe("function")
  expect(typeof client.corpusStatus).toBe("function")
  expect(typeof client.corpusTree).toBe("function")
  expect(typeof client.regexSearch).toBe("function")
  expect(typeof client.deleteDocument).toBe("function")
  expect(typeof client.citeRender).toBe("function")
  expect(typeof client.citeTree).toBe("function")
  expect(typeof client.doctor).toBe("function")
  expect(typeof client.shutdown).toBe("function")
})

test("BackendClient passes configured research paths to the backend", () => {
  const client = new BackendClient(
    "python3",
    "shutong_backend.rpc_server",
    "/tmp/daoism/corpus/.shutong",
    "test-model",
    undefined,
    "/tmp/daoism/.shutong/glossary",
    "/tmp/daoism/library",
  )
  const env = (client as any).requestEnv()
  expect(env.SHUTONG_CORPUS_ROOT).toBe("/tmp/daoism/corpus")
  expect(env.SHUTONG_GLOSSARY_DIR).toBe("/tmp/daoism/.shutong/glossary")
  expect(env.SHUTONG_LIBRARY_ROOT).toBe("/tmp/daoism/library")
})
