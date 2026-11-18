import type { ShutongConfig, LlmConfig, CompactionInfo } from "../shared/types"
import { BackendClient, BackendError } from "./backend-client"
import { MemoryStore, createMemoryEntry } from "./memory"
import { SessionStore } from "./session-store"
import type { ChatMessage } from "../shared/types"
import { mkdirSync, existsSync } from "fs"
import path from "path"

export class Engine {
  config: ShutongConfig
  memory: MemoryStore
  backend: BackendClient
  sessions: SessionStore

  constructor(config: ShutongConfig) {
    this.config = config
    const storageRoot = path.join(config.corpus_root, ".shutong")
    mkdirSync(storageRoot, { recursive: true })

    const sessionsDir = path.join(storageRoot, "sessions")
    const legacyMemoryDir = path.join(config.corpus_root, ".memory")
    this.memory = new MemoryStore(
      sessionsDir,
      existsSync(legacyMemoryDir) ? legacyMemoryDir : undefined,
    )

    this.backend = new BackendClient(
      config.python_bin,
      config.backend_module,
      storageRoot,
      config.llm.model,
      config.llm,
      config.glossary_dir,
      config.library_root,
    )

    this.sessions = new SessionStore(storageRoot)
  }

  async chat(prompt: string, threadId: string, continuation?: { continuation_id?: string; user_choice?: string; refinement?: string }): Promise<any> {
    const result = this.backend.chatContext(prompt, continuation)

    const answer = result?.answer_human ?? ""
    const kernelMemorySaved = result?.kernel_memory_save?.status === "ok"

    if (answer && !kernelMemorySaved) {
      const evidenceIds: string[] = result?.answer_machine?.evidence
        ?.filter((_: any) => true)
        ?.map((e: any) => e.node_id)
        ?.filter(Boolean) ?? []

      const entry = createMemoryEntry(threadId, prompt, answer, evidenceIds)
      this.memory.save(entry)

      // Auto-mine into MemPalace (fire-and-forget, non-blocking)
      this.mineToMemPalace(prompt, answer, threadId)
    }

    return result
  }

  async *chatStream(prompt: string, threadId: string): AsyncGenerator<any, any, void> {
    let finalResult: any
    for await (const event of this.backend.chatStream(threadId, prompt)) {
      if (event.event === "done") finalResult = event.data?.result
      yield event
    }

    const answer = finalResult?.answer_human ?? ""
    const kernelMemorySaved = finalResult?.kernel_memory_save?.status === "ok"
    if (answer && !kernelMemorySaved) {
      const evidenceIds: string[] = finalResult?.answer_machine?.evidence
        ?.map((e: any) => e.node_id)
        ?.filter(Boolean) ?? []
      this.memory.save(createMemoryEntry(threadId, prompt, answer, evidenceIds))
      this.mineToMemPalace(prompt, answer, threadId)
    }
    return finalResult
  }

  /** Auto-mine a Q&A pair into MemPalace (best-effort, non-blocking). */
  private mineToMemPalace(query: string, answer: string, threadId: string): void {
    try {
      const text = `Q: ${query}\nA: ${answer.slice(0, 1000)}`
      this.backend.mempalaceAdd(text, "shutong", threadId)
    } catch {
      // Best-effort — don't interrupt the user
    }
  }

  /** Wake-up: retrieve relevant memories for the current context. */
  mempalaceWakeUp(context = "", maxTokens = 300): any {
    try {
      return this.backend.mempalaceWakeUp(context, maxTokens)
    } catch {
      return { context: "" }
    }
  }

  /** Search the MemPalace knowledge base. */
  mempalaceSearch(query: string, topN = 10): any {
    try {
      return this.backend.mempalaceSearch(query, topN)
    } catch {
      return { results: "" }
    }
  }

  /** Get MemPalace status. */
  mempalaceStatus(): any {
    try {
      return this.backend.mempalaceStatus()
    } catch {
      return { status: "unavailable" }
    }
  }

  // ── Writing pipeline ──────────────────────────────────────────────

  writingOutline(topic: string, sources: string[] = []): any {
    return this.backend.writingOutline(topic, sources)
  }

  writingDraft(outline: Record<string, unknown>): any {
    return this.backend.writingDraft(outline)
  }

  writingStyle(draft: Record<string, unknown>): any {
    return this.backend.writingStyle(draft)
  }

  writingQuality(draft: Record<string, unknown>): any {
    return this.backend.writingQuality(draft)
  }

  // ── Passport ──────────────────────────────────────────────────────

  passportCreate(projectName: string, researchGoals?: string[]): any {
    return this.backend.passportCreate(projectName, researchGoals)
  }

  passportLoad(passportId: string): any {
    return this.backend.passportLoad(passportId)
  }

  passportUpdate(passportId: string, updates: Record<string, unknown>): any {
    return this.backend.passportUpdate(passportId, updates)
  }

  passportSummary(passportId: string): any {
    return this.backend.passportSummary(passportId)
  }

  passportList(): any {
    return this.backend.passportList()
  }

  // ── Knowledge graph ──────────────────────────────────────────────

  graphQuery(nodeId: string, depth = 2): any {
    return this.backend.graphQuery(nodeId, depth)
  }

  graphStats(): any {
    return this.backend.graphStats()
  }

  // ── Depth measurement ─────────────────────────────────────────────

  depthMeasure(message: string, evidenceIds: string[] = [], retrievedIds: string[] = []): any {
    return this.backend.depthMeasure(message, evidenceIds, retrievedIds)
  }

  // ── Devil's advocate ──────────────────────────────────────────────

  devilsAdvocate(answerHuman: string, answerMachine: Record<string, unknown> = {}): any {
    return this.backend.devilsAdvocate(answerHuman, answerMachine)
  }

  // ── Peer review ───────────────────────────────────────────────────

  review(draft: Record<string, unknown>): any {
    return this.backend.review(draft)
  }

  // ── Diary ─────────────────────────────────────────────────────────

  diarySave(params: { sessionId?: string; topicsDiscussed?: string[]; sourcesConsulted?: string[]; keyInsights?: string[]; openQuestions?: string[]; depthTrend?: string }): any {
    return this.backend.diarySave(params)
  }

  diaryLoad(date: string): any {
    return this.backend.diaryLoad(date)
  }

  diaryList(): any {
    return this.backend.diaryList()
  }

  diaryRecent(count = 5): any {
    return this.backend.diaryRecent(count)
  }


  async search(query: string): Promise<any> {
    return this.backend.search(query, 20)
  }

  // ── Code subagent ───────────────────────────────────────────────────

  codeSubagent(instruction: string, codeRoot?: string): any {
    return this.backend.codeSubagent(instruction, codeRoot ?? this.config.corpus_root)
  }

  codeFileRead(path: string, startLine?: number, endLine?: number): any {
    return this.backend.codeFileRead(path, startLine, endLine)
  }

  codeFileWrite(path: string, content: string): any {
    return this.backend.codeFileWrite(path, content)
  }

  codeFileEdit(path: string, oldString: string, newString: string, replaceAll = false): any {
    return this.backend.codeFileEdit(path, oldString, newString, replaceAll)
  }

  codeFileList(path = "."): any {
    return this.backend.codeFileList(path)
  }

  codeBash(command: string, timeout = 30, workdir?: string): any {
    return this.backend.codeBash(command, timeout, workdir)
  }

  codeGrep(pattern: string, path = ".", caseInsensitive = true, maxResults = 50): any {
    return this.backend.codeGrep(pattern, path, caseInsensitive, maxResults)
  }

  codeGlob(pattern: string, path = ".", maxResults = 100): any {
    return this.backend.codeGlob(pattern, path, maxResults)
  }

  // ── Context compaction ───────────────────────────────────────────────

  compactContext(messages: Record<string, unknown>[], thresholdPct = 0.8, maxTokens = 4000): any {
    return this.backend.compactContext(messages, thresholdPct, maxTokens)
  }

  /** Estimate tokens for a message list (~4 chars per token). */
  private estimateTokens(messages: { content: string }[]): number {
    return messages.reduce((sum, m) => sum + Math.max(1, Math.ceil(m.content.length / 4)), 0)
  }

  /** Auto-compact message history if it exceeds threshold. Returns compacted messages or original. */
  autoCompactIfNeeded<T extends { content: string }>(messages: T[], thresholdPct = 0.8): { messages: T[], compaction?: CompactionInfo } {
    const totalTokens = this.estimateTokens(messages)
    const maxTokens = this.config.llm.max_tokens
    if (totalTokens < maxTokens * thresholdPct) {
      return { messages }
    }
    try {
      const result = this.backend.compactContext(
        messages.map(m => ({ ...m })),
        thresholdPct,
        maxTokens,
      )
      if (result?.compacted && result?.messages) {
        return { messages: result.messages as T[], compaction: result.compaction_info as CompactionInfo }
      }
      return { messages }
    } catch {
      return { messages }
    }
  }

  // ── Permissions ───────────────────────────────────────────────────────

  permissionsCheck(tool: string, params: Record<string, unknown> = {}): any {
    return this.backend.permissionsCheck(tool, params)
  }

  permissionsList(): any {
    return this.backend.permissionsList()
  }

  permissionsSet(toolPattern: string, permission: "allow" | "ask" | "deny"): any {
    return this.backend.permissionsSet(toolPattern, permission)
  }

  async ingest(inputPath: string, extraArgs: string[] = []): Promise<any> {
    const options: Record<string, any> = {}
    const typeIdx = extraArgs.findIndex((a) => a === "--type" || a === "--doc-type-override")
    if (typeIdx >= 0 && typeIdx + 1 < extraArgs.length) options.doc_type = extraArgs[typeIdx + 1]
    return this.backend.ingest(inputPath, options)
  }

  memorySearch(query: string, threadId?: string) {
    return this.memory.search(query, threadId)
  }

  async shutdown(): Promise<void> {
    return this.backend.shutdown()
  }

  get corpusRoot(): string {
    return this.config.corpus_root
  }

  /** Hot-swap the LLM model and provider without restart. */
  setModel(provider: LlmConfig["provider"], model: string): void {
    this.config.llm.provider = provider
    this.config.llm.model = model
    // Update backend client's model and config
    ;(this.backend as any)._llmConfig = { ...this.config.llm }
    ;(this.backend as any).defaultModel = `${provider}/${model}`
    this.backend.switchProvider(provider, model).catch(() => {})
  }

  providers(): Promise<any> {
    return this.backend.providers()
  }
}

export { BackendClient, BackendError } from "./backend-client"
export { allTools, getTool, resolveToolCall } from "./tool-registry"
export type { ToolEntry } from "./tool-registry"
export type { BackendMethod, MethodParamsMap } from "./backend-types"
export { SessionStore } from "./session-store"
