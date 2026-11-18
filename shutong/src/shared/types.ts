// Config types
export interface ShutongConfig {
  corpus_root: string
  library_root: string
  glossary_dir: string
  python_bin: string
  backend_module: string
  llm: LlmConfig
  plugins: PluginsConfig
  memory: MemoryConfig
}

export interface LlmConfig {
  provider: "ollama" | "anthropic" | "openai"
  model: string
  temperature: number
  max_tokens: number
  apiKey?: string
  baseURL?: string
}

export interface PluginsConfig {
  directory: string
  enabled: string[]
}

export interface MemoryConfig {
  backend: string
  postgresql_url?: string
}

// Chat types — OpenCode-style message model
export type MessageRole = "user" | "assistant" | "system" | "tool"

export interface ChatMessage {
  role: MessageRole
  content: string
  citations: string[]
  toolName?: string
  toolCallId?: string
  timestamp?: number
  depthScore?: number
}

// Search types
export interface SearchResultEntry {
  title: string
  author: string
  text: string
  formatted_citation: string
  score: number
  node_id: string
}

// Session types
export interface SessionInfo {
  id: string
  title: string
  createdAt: number
  updatedAt: number
  messageCount: number
}

// Tool call types
export interface ToolCallInfo {
  name: string
  arguments: Record<string, unknown>
  result?: unknown
  error?: string
  status: "pending" | "running" | "complete" | "error"
}

// Pipeline checkpoint types — staged execution
export interface PipelineCheckpoint {
  pipeline_id: string
  stage_name: string
  stage_index: number
  intermediate_result: Record<string, unknown>
  question: string
  options: string[]
}

export interface PipelineResume {
  pipeline_id: string
  user_choice: "proceed" | "refine" | "abort"
  refinement?: string
}

export interface QualityCheck {
  check_type: string
  passed: boolean
  score: number
  detail: string
  violations: string[]
}

export interface QualityReport {
  status: "approved" | "flagged" | "rejected"
  checks: QualityCheck[]
  violations: string[]
  suggestions: string[]
  anti_flattery_score: number
  depth_score: number
}

// Engine IPC types (retained for compatibility)
export interface ChatRequest {
  operation: "chat"
  prompt: string
  thread_id: string
  corpus_root: string
  llm_model: string
}

// Context compaction types
export interface CompactionInfo {
  original_count: number
  compacted_count: number
  tokens_saved: number
}

// Permission types
export type PermissionLevel = "allow" | "ask" | "deny"

export interface PermissionRule {
  tool_pattern: string
  permission: PermissionLevel
}
