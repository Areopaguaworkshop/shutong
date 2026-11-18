import { mkdirSync, appendFileSync, readFileSync, readdirSync, existsSync } from "fs"
import path from "path"
import { createHash } from "crypto"

export interface MemoryEntry {
  entry_id: string
  timestamp: string
  thread_id: string
  query: string
  response: string
  evidence_node_ids: string[]
  sha256: string
}

export function createMemoryEntry(
  threadId: string,
  query: string,
  response: string,
  evidenceNodeIds: string[],
): MemoryEntry {
  const timestamp = new Date().toISOString()
  const payload = `${timestamp}|${query}|${response}`
  const hash = createHash("sha256").update(payload).digest("hex")
  const entryId = hash.slice(0, 16)

  return {
    entry_id: entryId,
    timestamp,
    thread_id: threadId,
    query,
    response,
    evidence_node_ids: evidenceNodeIds,
    sha256: hash,
  }
}

export class MemoryStore {
  private memoryDir: string
  private legacyMemoryDir?: string

  constructor(memoryDir: string, legacyMemoryDir?: string) {
    this.memoryDir = memoryDir
    this.legacyMemoryDir = legacyMemoryDir
    mkdirSync(memoryDir, { recursive: true })
  }

  save(entry: MemoryEntry): void {
    const filePath = this.threadPath(entry.thread_id)
    const line = JSON.stringify(entry)
    appendFileSync(filePath, line + "\n")
  }

  loadThread(threadId: string): MemoryEntry[] {
    const byId = new Map<string, MemoryEntry>()

    if (this.legacyMemoryDir) {
      for (const entry of this.loadThreadFromDir(this.legacyMemoryDir, threadId)) {
        byId.set(entry.entry_id, entry)
      }
    }
    for (const entry of this.loadThreadFromDir(this.memoryDir, threadId)) {
      byId.set(entry.entry_id, entry)
    }

    return Array.from(byId.values()).sort((a, b) => a.timestamp.localeCompare(b.timestamp))
  }

  search(query: string, threadId?: string): MemoryEntry[] {
    const queryLower = query.toLowerCase()
    const keywords = queryLower.split(/\s+/).filter(Boolean)
    if (keywords.length === 0) return []

    const threads = threadId ? [threadId] : this.listThreads()

    const results: Array<[number, MemoryEntry]> = []
    for (const tid of threads) {
      for (const entry of this.loadThread(tid)) {
        const text = `${entry.query} ${entry.response}`.toLowerCase()
        const hits = keywords.filter(kw => text.includes(kw)).length
        if (hits > 0) results.push([hits, entry])
      }
    }

    return results.sort((a, b) => b[0] - a[0]).map(([, e]) => e)
  }

  listThreads(): string[] {
    const threads = new Set<string>()
    if (this.legacyMemoryDir) this.collectThreadNames(this.legacyMemoryDir, threads)
    this.collectThreadNames(this.memoryDir, threads)
    return Array.from(threads).sort()
  }

  private loadThreadFromDir(dir: string, threadId: string): MemoryEntry[] {
    const filePath = this.threadPathInDir(dir, threadId)
    if (!existsSync(filePath)) return []

    const content = readFileSync(filePath, "utf-8")
    return content
      .split("\n")
      .filter(line => line.trim())
      .map(line => {
        try { return JSON.parse(line) as MemoryEntry }
        catch { return null }
      })
      .filter((e): e is MemoryEntry => e !== null)
  }

  private collectThreadNames(dir: string, threads: Set<string>): void {
    if (!existsSync(dir)) return
    for (const name of readdirSync(dir)) {
      if (name.endsWith(".jsonl")) threads.add(name.replace(/\.jsonl$/, ""))
    }
  }

  private threadPath(threadId: string): string {
    return this.threadPathInDir(this.memoryDir, threadId)
  }

  private threadPathInDir(dir: string, threadId: string): string {
    const safe = threadId.replace(/[^a-zA-Z0-9\-_]/g, "_")
    return path.join(dir, `${safe}.jsonl`)
  }

  /**
   * MemPalace-backed semantic search — enhances keyword search with
   * vector similarity when a BackendClient is available.
   *
   * Falls back to keyword-only results when MemPalace is unreachable.
   */
  async mempalaceSearch(
    query: string,
    threadId?: string,
    backend?: { mempalaceSearch: (q: string, n: number) => any },
  ): Promise<MemoryEntry[]> {
    // First get keyword results
    const keywordResults = this.search(query, threadId)

    if (!backend) return keywordResults

    try {
      const mpResult = backend.mempalaceSearch(query, 15)
      // MemPalace returns text — we can't easily map back to MemoryEntry
      // so we just use it as augmentation. For now, return keyword results.
      // Phase 6 will add proper cross-referencing.
      return keywordResults
    } catch {
      return keywordResults
    }
  }
}