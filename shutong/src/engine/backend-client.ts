import { spawnSync } from "bun"
import { randomBytes } from "node:crypto"
import { existsSync } from "fs"
import net from "node:net"
import path from "path"
import type { BackendMethod, RpcResponse } from "./backend-types"
import type { LlmConfig } from "../shared/types"

/** Create a per-daemon bearer token. In-memory only; never log or persist it. */
export function createDaemonToken(): string {
  return randomBytes(32).toString("hex")
}

export interface BackendStreamEvent {
  id?: string
  event: "message.part.updated" | "tool.call" | "tool.result" | "stage" | "permission.required" | "error" | "done" | string
  data: any
}

/** Backend error thrown when the Python process fails or returns an error. */
export class BackendError extends Error {
  readonly code: string
  readonly nextAction?: string
  constructor(code: string, message: string, nextAction?: string) {
    super(message)
    this.code = code
    this.nextAction = nextAction
  }
}

/**
 * RPC client for the Shutong Python backend.
 *
 * Communicates via a stateless spawn-per-request model using environment
 * variables for request metadata and NDJSON on stdout. This is the proven
 * transport that works reliably with Bun's subprocess handling.
 *
 * Each call spawns a Python process that runs the RPC method and returns
 * a single JSON response line. The backend surface is method-oriented
 * and deterministic.
 */
export class BackendClient {
  private _llmConfig: LlmConfig
  private daemonUrl?: string
  private daemonToken?: string
  private daemonProc?: ReturnType<typeof Bun.spawn>

  constructor(
    private pythonBin: string,
    private module: string,
    private storageDir: string,
    private defaultModel: string,
    llmConfig?: LlmConfig,
    private glossaryDir = ".shutong/glossary",
    private libraryDir = "library",
  ) {
    this._llmConfig = llmConfig ?? {
      provider: "ollama",
      model: defaultModel,
      temperature: 0.1,
      max_tokens: 4096,
    }
  }

  private backendPythonPath(): string | undefined {
    const packageRoot = path.resolve(import.meta.dir, "../../../packages/shutong-backend")
    if (!existsSync(packageRoot)) return undefined
    const current = process.env.PYTHONPATH
    return current ? `${packageRoot}:${current}` : packageRoot
  }

  private requestEnv(): Record<string, string> {
    const env: Record<string, string> = {
      ...process.env as Record<string, string>,
      SHUTONG_STORAGE_DIR: this.storageDir,
      SHUTONG_CORPUS_ROOT: path.dirname(this.storageDir),
      SHUTONG_LLM_MODEL: this.defaultModel,
      SHUTONG_GLOSSARY_DIR: this.glossaryDir,
      SHUTONG_LIBRARY_ROOT: this.libraryDir,
      CITEINDEX_STORAGE_DIR: this.storageDir,
      CITEAGENT_CORPUS_ROOT: path.dirname(this.storageDir),
      CITEINDEX_LLM_MODEL: this.defaultModel,
    }

    if (this._llmConfig) {
      env.SHUTONG_LLM_PROVIDER = this._llmConfig.provider
      if (this._llmConfig.apiKey) env.SHUTONG_API_KEY = this._llmConfig.apiKey
      if (this._llmConfig.baseURL) env.SHUTONG_LLM_BASE_URL = this._llmConfig.baseURL
    }

    const pythonPath = this.backendPythonPath()
    if (pythonPath) env.PYTHONPATH = pythonPath
    return env
  }

  private daemonAuthHeaders(): Record<string, string> {
    return this.daemonToken ? { authorization: `Bearer ${this.daemonToken}` } : {}
  }

  private request(method: BackendMethod, params: Record<string, unknown> = {}): any {
    const id = crypto.randomUUID()
    const env: Record<string, string> = {
      ...this.requestEnv(),
      SHUTONG_RPC_METHOD: method,
      SHUTONG_RPC_PARAMS: JSON.stringify(params),
    }

    const proc = spawnSync({
      cmd: [
        this.pythonBin,
        "-u",
        "-c",
        "import asyncio, json, os; from shutong_backend.rpc_server import _handle; result = asyncio.run(_handle(os.environ['SHUTONG_RPC_METHOD'], json.loads(os.environ['SHUTONG_RPC_PARAMS']))); print(json.dumps({'id': 'local', 'result': result}, ensure_ascii=False))",
      ],
      env,
    })

    const stderr = proc.stderr.toString().trim()
    if (proc.exitCode !== 0) {
      throw new BackendError("process_error", stderr || `Backend exited with code ${proc.exitCode}`)
    }

    const stdout = proc.stdout.toString().trim()
    const firstLine = stdout.split("\n").find((line: string) => line.trim().length > 0)
    if (!firstLine) {
      throw new BackendError("empty_response", "Backend returned no response")
    }

    const message = JSON.parse(firstLine) as RpcResponse
    if (message.error) {
      throw new BackendError(
        message.error.code ?? "unknown",
        message.error.message ?? "Unknown backend error",
        message.error.next_action,
      )
    }
    return message.result
  }

  private async freePort(): Promise<number> {
    return await new Promise((resolve, reject) => {
      const server = net.createServer()
      server.on("error", reject)
      server.listen(0, "127.0.0.1", () => {
        const address = server.address()
        const port = typeof address === "object" && address ? address.port : 0
        server.close(() => resolve(port))
      })
    })
  }

  private async ensureDaemon(): Promise<string> {
    if (this.daemonUrl) return this.daemonUrl
    const port = await this.freePort()
    const url = `http://127.0.0.1:${port}`
    this.daemonToken = createDaemonToken()
    this.daemonProc = Bun.spawn({
      cmd: [this.pythonBin, "-u", "-m", "shutong_backend.server", "--host", "127.0.0.1", "--port", String(port)],
      env: { ...this.requestEnv(), SHUTONG_HTTP_TOKEN: this.daemonToken },
      stdout: "pipe",
      stderr: "pipe",
    })

    for (let i = 0; i < 80; i += 1) {
      try {
        const response = await fetch(`${url}/health`, { headers: this.daemonAuthHeaders() })
        if (response.ok) {
          this.daemonUrl = url
          return url
        }
      } catch {
        // daemon is still starting
      }
      await new Promise((resolve) => setTimeout(resolve, 50))
    }
    throw new BackendError("daemon_start_failed", "Shutong daemon did not become healthy")
  }

  private async daemonJson(pathname: string, init?: RequestInit): Promise<any> {
    const url = await this.ensureDaemon()
    const response = await fetch(`${url}${pathname}`, {
      ...init,
      headers: { "content-type": "application/json", ...this.daemonAuthHeaders(), ...(init?.headers ?? {}) },
    })
    const text = await response.text()
    const data = text ? JSON.parse(text) : {}
    if (!response.ok) {
      throw new BackendError(data?.code ?? "http_error", data?.message ?? `HTTP ${response.status}`)
    }
    return data
  }

  private parseSseFrame(frame: string): BackendStreamEvent | undefined {
    let id: string | undefined
    let event = "message"
    const dataLines: string[] = []
    for (const line of frame.split("\n")) {
      if (line.startsWith(":")) continue
      if (line.startsWith("id:")) id = line.slice(3).trim()
      else if (line.startsWith("event:")) event = line.slice(6).trim()
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart())
    }
    if (dataLines.length === 0) return undefined
    return { id, event, data: JSON.parse(dataLines.join("\n")) }
  }

  async *chatStream(sessionId: string, prompt: string): AsyncGenerator<BackendStreamEvent, any, void> {
    const url = await this.ensureDaemon()
    const session = await this.daemonJson("/session", { method: "POST", body: JSON.stringify({ id: sessionId }) })
    const eventResponsePromise = fetch(`${url}/session/${encodeURIComponent(sessionId)}/event?once=1`, {
      headers: { accept: "text/event-stream", "Last-Event-ID": String(session.last_event_id ?? 0), ...this.daemonAuthHeaders() },
    })
    await this.daemonJson(`/session/${encodeURIComponent(sessionId)}/message`, {
      method: "POST",
      body: JSON.stringify({ prompt }),
    })

    const eventResponse = await eventResponsePromise
    if (!eventResponse.ok || !eventResponse.body) {
      throw new BackendError("stream_error", `SSE stream failed with HTTP ${eventResponse.status}`)
    }
    const reader = eventResponse.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ""
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const frames = buffer.split("\n\n")
      buffer = frames.pop() ?? ""
      for (const frame of frames) {
        const event = this.parseSseFrame(frame)
        if (!event) continue
        yield event
        if (event.event === "done") return event.data?.result
      }
    }
    return undefined
  }

  async providers(): Promise<any> {
    return this.daemonJson("/providers")
  }

  async switchProvider(provider: string, model: string): Promise<any> {
    return this.daemonJson("/provider/switch", { method: "POST", body: JSON.stringify({ provider, model }) })
  }

  // ── Typed RPC methods ──────────────────────────────────────────

  health(): any {
    return this.request("health")
  }

  doctor(projectRoot?: string): any {
    return this.request("doctor", { project_root: projectRoot })
  }

  search(query: string, topK = 20): any {
    return this.request("search", { query, top_k: topK })
  }

  chatContext(prompt: string, continuation?: { continuation_id?: string; user_choice?: string; refinement?: string }): any {
    const params: Record<string, unknown> = { prompt }
    if (continuation?.continuation_id) params.continuation_id = continuation.continuation_id
    if (continuation?.user_choice) params.user_choice = continuation.user_choice
    if (continuation?.refinement) params.refinement = continuation.refinement
    return this.request("chat_context", params)
  }

  /** @deprecated Use chatContext for method-oriented access. */
  chat(prompt: string): any {
    return this.chatContext(prompt)
  }

  ingest(source: string, options: Record<string, any> = {}): any {
    return this.request("ingest", { source, ...options })
  }

  ingestStatus(): any {
    return this.request("ingest_status")
  }

  verifyDocument(cslId: string, nodeHash?: string): any {
    return this.request("verify_document", { csl_id: cslId, node_hash: nodeHash })
  }

  verifyAll(): any {
    return this.request("verify_all")
  }

  resolveCitation(citationKey: string): any {
    return this.request("resolve_citation", { citation_key: citationKey })
  }

  translate(source: string, glossaryFiles?: string[]): any {
    return this.request("translate", { source, glossary_files: glossaryFiles })
  }

  renderBilingual(cslId: string, outputFormat = "interleaved"): any {
    return this.request("render_bilingual", { csl_id: cslId, output_format: outputFormat })
  }

  glossaryLookup(terms: string[]): any {
    return this.request("glossary_lookup", { terms })
  }

  glossaryAdd(termEn: string, termZh: string, file?: string): any {
    return this.request("glossary_add", { term_en: termEn, term_zh: termZh, file })
  }

  glossaryList(): any {
    return this.request("glossary_list")
  }

  memorySearch(query: string, threadId?: string): any {
    return this.request("memory_search", { query, thread_id: threadId })
  }

  memorySave(title: string, content: string, tags?: string[]): any {
    return this.request("memory_save", { title, content, tags })
  }

  corpusStatus(): any {
    return this.request("corpus_status")
  }

  corpusTree(): any {
    return this.request("corpus_tree")
  }

  regexSearch(pattern: string, field = "text"): any {
    return this.request("regex_search", { pattern, field })
  }

  deleteDocument(cslId: string): any {
    return this.request("delete_document", { csl_id: cslId })
  }

  citeRender(cslId: string, style = "chicago-author-date"): any {
    return this.request("cite_render", { csl_id: cslId, style })
  }

  citeTree(cslId: string): any {
    return this.request("cite_tree", { csl_id: cslId })
  }


  mempalaceSearch(query: string, topN = 10): any {
    return this.request("mempalace_search", { query, top_n: topN })
  }

  mempalaceWakeUp(context = "", maxTokens = 300): any {
    return this.request("mempalace_wake_up", { context, max_tokens: maxTokens })
  }

  mempalaceStatus(): any {
    return this.request("mempalace_status")
  }

  mempalaceAdd(text: string, wing = "shutong", room = "general"): any {
    return this.request("mempalace_add", { text, wing, room })
  }

  mempalaceInstructions(): any {
    return this.request("mempalace_instructions")
  }

  mempalaceCompress(): any {
    return this.request("mempalace_compress")
  }

  // ── Writing pipeline ──────────────────────────────────────────────

  writingOutline(topic: string, sources: string[] = []): any {
    return this.request("writing_outline", { topic, sources })
  }

  writingDraft(outline: Record<string, unknown>): any {
    return this.request("writing_draft", { outline })
  }

  writingStyle(draft: Record<string, unknown>): any {
    return this.request("writing_style", { draft })
  }

  writingQuality(draft: Record<string, unknown>): any {
    return this.request("writing_quality", { draft })
  }

  // ── Passport ──────────────────────────────────────────────────────

  passportCreate(projectName = "Untitled Project", researchGoals?: string[]): any {
    const params: Record<string, unknown> = { project_name: projectName }
    if (researchGoals) params.research_goals = researchGoals
    return this.request("passport_create", params)
  }

  passportLoad(passportId: string): any {
    return this.request("passport_load", { passport_id: passportId })
  }

  passportUpdate(passportId: string, updates: Record<string, unknown>): any {
    return this.request("passport_update", { passport_id: passportId, updates })
  }

  passportSummary(passportId: string, maxTokens = 500): any {
    return this.request("passport_summary", { passport_id: passportId, max_tokens: maxTokens })
  }

  passportList(): any {
    return this.request("passport_list")
  }

  // ── Knowledge graph ──────────────────────────────────────────────

  graphQuery(nodeId: string, depth = 2): any {
    return this.request("graph_query", { node_id: nodeId, depth })
  }

  graphStats(): any {
    return this.request("graph_stats")
  }

  // ── Depth measurement ──────────────────────────────────────────────

  depthMeasure(message: string, evidenceIds: string[] = [], retrievedIds: string[] = []): any {
    return this.request("depth_measure", { message, evidence_ids: evidenceIds, retrieved_ids: retrievedIds })
  }

  // ── Devil's advocate ──────────────────────────────────────────────

  devilsAdvocate(answerHuman: string, answerMachine: Record<string, unknown> = {}): any {
    return this.request("devils_advocate", { answer_human: answerHuman, answer_machine: answerMachine })
  }

  // ── Peer review ──────────────────────────────────────────────────────

  review(draft: Record<string, unknown>): any {
    return this.request("review", { draft })
  }

  // ── Diary ──────────────────────────────────────────────────────────

  diarySave(params: { sessionId?: string; topicsDiscussed?: string[]; sourcesConsulted?: string[]; keyInsights?: string[]; openQuestions?: string[]; depthTrend?: string }): any {
    return this.request("diary_save", {
      session_id: params.sessionId ?? "",
      topics_discussed: params.topicsDiscussed ?? [],
      sources_consulted: params.sourcesConsulted ?? [],
      key_insights: params.keyInsights ?? [],
      open_questions: params.openQuestions ?? [],
      depth_trend: params.depthTrend ?? "stable",
    })
  }

  diaryLoad(date: string): any {
    return this.request("diary_load", { date })
  }

  diaryList(): any {
    return this.request("diary_list")
  }

  diaryRecent(count = 5): any {
    return this.request("diary_recent", { count })
  }

  // ── Code subagent ──────────────────────────────────────────────────

  codeSubagent(instruction: string, codeRoot?: string): any {
    const params: Record<string, unknown> = { instruction }
    if (codeRoot) params.code_root = codeRoot
    return this.request("code_subagent", params)
  }

  codeFileRead(path: string, startLine?: number, endLine?: number): any {
    const params: Record<string, unknown> = { path }
    if (startLine !== undefined) params.start_line = startLine
    if (endLine !== undefined) params.end_line = endLine
    return this.request("code_file_read", params)
  }

  codeFileWrite(path: string, content: string): any {
    return this.request("code_file_write", { path, content })
  }

  codeFileEdit(path: string, oldString: string, newString: string, replaceAll = false): any {
    return this.request("code_file_edit", { path, old_string: oldString, new_string: newString, replace_all: replaceAll })
  }

  codeFileList(path = "."): any {
    return this.request("code_file_list", { path })
  }

  codeBash(command: string, timeout = 30, workdir?: string): any {
    const params: Record<string, unknown> = { command, timeout }
    if (workdir) params.workdir = workdir
    return this.request("code_bash", params)
  }

  codeGrep(pattern: string, path = ".", caseInsensitive = true, maxResults = 50): any {
    return this.request("code_grep", { pattern, path, case_insensitive: caseInsensitive, max_results: maxResults })
  }

  codeGlob(pattern: string, path = ".", maxResults = 100): any {
    return this.request("code_glob", { pattern, path, max_results: maxResults })
  }

  // ── Context compaction ──────────────────────────────────────────────

  compactContext(messages: Record<string, unknown>[], thresholdPct = 0.8, maxTokens = 4000): any {
    return this.request("compact_context", { messages, threshold_pct: thresholdPct, max_tokens: maxTokens })
  }

  // ── Permissions ──────────────────────────────────────────────────────

  permissionsCheck(tool: string, params: Record<string, unknown> = {}): any {
    return this.request("permissions_check", { tool, params })
  }

  permissionsList(): any {
    return this.request("permissions_list")
  }

  permissionsSet(toolPattern: string, permission: "allow" | "ask" | "deny"): any {
    return this.request("permissions_set", { tool_pattern: toolPattern, permission })
  }

  async shutdown(): Promise<void> {
    this.daemonProc?.kill()
    this.daemonProc = undefined
    this.daemonUrl = undefined
    this.daemonToken = undefined
  }
}
