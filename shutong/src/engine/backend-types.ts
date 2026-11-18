import { z } from "zod"

// ─── RPC Transport ────────────────────────────────────────────────

export const RpcRequestSchema = z.object({
  id: z.string(),
  method: z.string(),
  params: z.record(z.string(), z.unknown()).default({}),
})
export type RpcRequest = z.infer<typeof RpcRequestSchema>

export const RpcErrorSchema = z.object({
  code: z.string(),
  message: z.string(),
  next_action: z.string().optional(),
})
export type RpcError = z.infer<typeof RpcErrorSchema>

export const RpcResponseSchema = z.object({
  id: z.string(),
  result: z.unknown().optional(),
  error: RpcErrorSchema.optional(),
})
export type RpcResponse = z.infer<typeof RpcResponseSchema>

// ─── Method names ─────────────────────────────────────────────────

export type BackendMethod =
  | "health"
  | "search"
  | "chat_context"
  | "ingest"
  | "ingest_status"
  | "verify_document"
  | "verify_all"
  | "resolve_citation"
  | "translate"
  | "render_bilingual"
  | "glossary_lookup"
  | "glossary_add"
  | "glossary_list"
  | "memory_search"
  | "memory_save"
  | "corpus_status"
  | "corpus_tree"
  | "doctor"
  | "regex_search"
  | "delete_document"
  | "cite_render"
  | "cite_tree"
  | "mempalace_search"
  | "mempalace_wake_up"
  | "mempalace_status"
  | "mempalace_add"
  | "mempalace_instructions"
  | "mempalace_compress"
  | "writing_outline"
  | "writing_draft"
  | "writing_style"
  | "writing_quality"
  | "passport_create"
  | "passport_load"
  | "passport_update"
  | "passport_summary"
  | "passport_list"
  | "graph_query"
  | "graph_stats"
  | "depth_measure"
  | "devils_advocate"
  | "review"
  | "diary_save"
  | "diary_load"
  | "diary_list"
  | "diary_recent"
  | "code_subagent"
  | "tool_call"
  | "code_file_read"
  | "code_file_write"
  | "code_file_edit"
  | "code_file_list"
  | "code_bash"
  | "code_grep"
  | "code_glob"
  | "compact_context"
  | "permissions_check"
  | "permissions_list"
  | "permissions_set"

// ─── Request params (typed) ──────────────────────────────────────

export const HealthParams = z.object({}).default({})
export type HealthParams = z.infer<typeof HealthParams>

export const SearchParams = z.object({
  query: z.string(),
  top_k: z.number().default(20),
})
export type SearchParams = z.infer<typeof SearchParams>

export const ChatContextParams = z.object({
  prompt: z.string(),
  continuation_id: z.string().optional(),
  user_choice: z.enum(["proceed", "refine", "abort"]).optional(),
  refinement: z.string().optional(),
})
export type ChatContextParams = z.infer<typeof ChatContextParams>

export const IngestParams = z.object({
  source: z.string(),
  text_direction: z.enum(["horizontal", "vertical"]).default("horizontal"),
  lang: z.string().default("auto"),
  is_primary: z.boolean().default(false),
  doc_type: z.string().optional(),
})
export type IngestParams = z.infer<typeof IngestParams>

export const IngestStatusParams = z.object({}).default({})
export type IngestStatusParams = z.infer<typeof IngestStatusParams>

export const VerifyDocumentParams = z.object({
  csl_id: z.string(),
  node_hash: z.string().optional(),
})
export type VerifyDocumentParams = z.infer<typeof VerifyDocumentParams>

export const VerifyAllParams = z.object({}).default({})
export type VerifyAllParams = z.infer<typeof VerifyAllParams>

export const ResolveCitationParams = z.object({
  citation_key: z.string(),
})
export type ResolveCitationParams = z.infer<typeof ResolveCitationParams>

export const TranslateParams = z.object({
  source: z.string(),
  glossary_files: z.array(z.string()).optional(),
})
export type TranslateParams = z.infer<typeof TranslateParams>

export const RenderBilingualParams = z.object({
  csl_id: z.string(),
  output_format: z.enum(["interleaved", "side_by_side", "parallel"]).default("interleaved"),
})
export type RenderBilingualParams = z.infer<typeof RenderBilingualParams>

export const GlossaryLookupParams = z.object({
  terms: z.array(z.string()),
})
export type GlossaryLookupParams = z.infer<typeof GlossaryLookupParams>

export const GlossaryAddParams = z.object({
  term_en: z.string(),
  term_zh: z.string(),
  file: z.string().optional(),
})
export type GlossaryAddParams = z.infer<typeof GlossaryAddParams>

export const GlossaryListParams = z.object({}).default({})
export type GlossaryListParams = z.infer<typeof GlossaryListParams>

export const MemorySearchParams = z.object({
  query: z.string(),
  thread_id: z.string().optional(),
})
export type MemorySearchParams = z.infer<typeof MemorySearchParams>

export const MemorySaveParams = z.object({
  title: z.string(),
  content: z.string(),
  tags: z.array(z.string()).optional(),
})
export type MemorySaveParams = z.infer<typeof MemorySaveParams>

export const CorpusStatusParams = z.object({}).default({})
export type CorpusStatusParams = z.infer<typeof CorpusStatusParams>

export const CorpusTreeParams = z.object({}).default({})
export type CorpusTreeParams = z.infer<typeof CorpusTreeParams>

export const DoctorParams = z.object({
  project_root: z.string().optional(),
})
export type DoctorParams = z.infer<typeof DoctorParams>

export const RegexSearchParams = z.object({
  pattern: z.string(),
  field: z.string().default("text"),
})
export type RegexSearchParams = z.infer<typeof RegexSearchParams>

export const DeleteDocumentParams = z.object({
  csl_id: z.string(),
})
export type DeleteDocumentParams = z.infer<typeof DeleteDocumentParams>

export const CiteRenderParams = z.object({
  csl_id: z.string(),
  style: z.string().default("chicago-author-date"),
})
export type CiteRenderParams = z.infer<typeof CiteRenderParams>

export const CiteTreeParams = z.object({
  csl_id: z.string(),
})
export type CiteTreeParams = z.infer<typeof CiteTreeParams>


export const MemPalaceSearchParams = z.object({
  query: z.string(),
  top_n: z.number().default(10),
})
export type MemPalaceSearchParams = z.infer<typeof MemPalaceSearchParams>

export const MemPalaceWakeUpParams = z.object({
  context: z.string().default(""),
  max_tokens: z.number().default(300),
})
export type MemPalaceWakeUpParams = z.infer<typeof MemPalaceWakeUpParams>

export const MemPalaceStatusParams = z.object({}).default({})
export type MemPalaceStatusParams = z.infer<typeof MemPalaceStatusParams>

export const MemPalaceAddParams = z.object({
  wing: z.string().default("shutong"),
  room: z.string().default("general"),
  text: z.string(),
})
export type MemPalaceAddParams = z.infer<typeof MemPalaceAddParams>

export const MemPalaceInstructionsParams = z.object({}).default({})
export type MemPalaceInstructionsParams = z.infer<typeof MemPalaceInstructionsParams>

export const MemPalaceCompressParams = z.object({}).default({})
export type MemPalaceCompressParams = z.infer<typeof MemPalaceCompressParams>

// ─── Writing pipeline params ──────────────────────────────────────

export const WritingOutlineParams = z.object({
  topic: z.string(),
  sources: z.array(z.string()).default([]),
})
export type WritingOutlineParams = z.infer<typeof WritingOutlineParams>

export const WritingDraftParams = z.object({
  outline: z.record(z.string(), z.unknown()).default({}),
})
export type WritingDraftParams = z.infer<typeof WritingDraftParams>

export const WritingStyleParams = z.object({
  draft: z.record(z.string(), z.unknown()).default({}),
})
export type WritingStyleParams = z.infer<typeof WritingStyleParams>

export const WritingQualityParams = z.object({
  draft: z.record(z.string(), z.unknown()).default({}),
})
export type WritingQualityParams = z.infer<typeof WritingQualityParams>

// ─── Passport params ──────────────────────────────────────────────

export const PassportCreateParams = z.object({
  project_name: z.string().default("Untitled Project"),
  research_goals: z.array(z.string()).optional(),
})
export type PassportCreateParams = z.infer<typeof PassportCreateParams>

export const PassportLoadParams = z.object({
  passport_id: z.string(),
})
export type PassportLoadParams = z.infer<typeof PassportLoadParams>

export const PassportUpdateParams = z.object({
  passport_id: z.string(),
  updates: z.record(z.string(), z.unknown()).default({}),
})
export type PassportUpdateParams = z.infer<typeof PassportUpdateParams>

export const PassportSummaryParams = z.object({
  passport_id: z.string(),
  max_tokens: z.number().default(500),
})
export type PassportSummaryParams = z.infer<typeof PassportSummaryParams>

export const PassportListParams = z.object({}).default({})
export type PassportListParams = z.infer<typeof PassportListParams>

// ─── Knowledge graph params ──────────────────────────────────────

export const GraphQueryParams = z.object({
  node_id: z.string(),
  depth: z.number().default(2),
})
export type GraphQueryParams = z.infer<typeof GraphQueryParams>

export const GraphStatsParams = z.object({}).default({})
export type GraphStatsParams = z.infer<typeof GraphStatsParams>

// ─── Depth measurement params ─────────────────────────────────────

export const DepthMeasureParams = z.object({
  message: z.string(),
  evidence_ids: z.array(z.string()).default([]),
  retrieved_ids: z.array(z.string()).default([]),
})
export type DepthMeasureParams = z.infer<typeof DepthMeasureParams>

// ─── Devil's advocate params ──────────────────────────────────────

export const DevilsAdvocateParams = z.object({
  answer_human: z.string(),
  answer_machine: z.record(z.string(), z.unknown()).default({}),
})
export type DevilsAdvocateParams = z.infer<typeof DevilsAdvocateParams>

// ─── Peer review params ───────────────────────────────────────────

export const ReviewParams = z.object({
  draft: z.record(z.string(), z.unknown()).default({}),
})
export type ReviewParams = z.infer<typeof ReviewParams>

// ─── Diary params ─────────────────────────────────────────────────

export const DiarySaveParams = z.object({
  session_id: z.string().default(""),
  topics_discussed: z.array(z.string()).default([]),
  sources_consulted: z.array(z.string()).default([]),
  key_insights: z.array(z.string()).default([]),
  open_questions: z.array(z.string()).default([]),
  depth_trend: z.string().default("stable"),
  passport_updates: z.record(z.string(), z.unknown()).default({}),
})
export type DiarySaveParams = z.infer<typeof DiarySaveParams>

export const DiaryLoadParams = z.object({
  date: z.string(),
})
export type DiaryLoadParams = z.infer<typeof DiaryLoadParams>

export const DiaryListParams = z.object({}).default({})
export type DiaryListParams = z.infer<typeof DiaryListParams>

export const DiaryRecentParams = z.object({
  count: z.number().default(5),
})
export type DiaryRecentParams = z.infer<typeof DiaryRecentParams>

// ─── Code subagent params ───────────────────────────────────────────

export const CodeSubagentParams = z.object({
  instruction: z.string(),
  code_root: z.string().optional(),
})
export type CodeSubagentParams = z.infer<typeof CodeSubagentParams>

export const CodeFileReadParams = z.object({
  path: z.string(),
  start_line: z.number().optional(),
  end_line: z.number().optional(),
})
export type CodeFileReadParams = z.infer<typeof CodeFileReadParams>

export const CodeFileWriteParams = z.object({
  path: z.string(),
  content: z.string(),
})
export type CodeFileWriteParams = z.infer<typeof CodeFileWriteParams>

export const CodeFileEditParams = z.object({
  path: z.string(),
  old_string: z.string(),
  new_string: z.string(),
  replace_all: z.boolean().default(false),
})
export type CodeFileEditParams = z.infer<typeof CodeFileEditParams>

export const CodeFileListParams = z.object({
  path: z.string().default("."),
})
export type CodeFileListParams = z.infer<typeof CodeFileListParams>

export const CodeBashParams = z.object({
  command: z.string(),
  timeout: z.number().default(30),
  workdir: z.string().optional(),
})
export type CodeBashParams = z.infer<typeof CodeBashParams>

export const CodeGrepParams = z.object({
  pattern: z.string(),
  path: z.string().default("."),
  case_insensitive: z.boolean().default(true),
  max_results: z.number().default(50),
})
export type CodeGrepParams = z.infer<typeof CodeGrepParams>

export const CodeGlobParams = z.object({
  pattern: z.string(),
  path: z.string().default("."),
  max_results: z.number().default(100),
})
export type CodeGlobParams = z.infer<typeof CodeGlobParams>

// ─── Context compaction params ──────────────────────────────────────

export const CompactContextParams = z.object({
  messages: z.array(z.record(z.string(), z.unknown())).default([]),
  threshold_pct: z.number().default(0.8),
  max_tokens: z.number().default(4000),
})
export type CompactContextParams = z.infer<typeof CompactContextParams>

export interface CompactionInfo {
  original_count: number
  compacted_count: number
  tokens_saved: number
}

// ─── Permission params ──────────────────────────────────────────────

export const PermissionsCheckParams = z.object({
  tool: z.string(),
  params: z.record(z.string(), z.unknown()).default({}),
})
export type PermissionsCheckParams = z.infer<typeof PermissionsCheckParams>

export const PermissionsListParams = z.object({}).default({})
export type PermissionsListParams = z.infer<typeof PermissionsListParams>

export const PermissionsSetParams = z.object({
  tool_pattern: z.string(),
  permission: z.enum(["allow", "ask", "deny"]),
})
export type PermissionsSetParams = z.infer<typeof PermissionsSetParams>

// ─── Backend method → params mapping ─────────────────────────────

export interface MethodParamsMap {
  health: HealthParams
  search: SearchParams
  chat_context: ChatContextParams
  ingest: IngestParams
  ingest_status: IngestStatusParams
  verify_document: VerifyDocumentParams
  verify_all: VerifyAllParams
  resolve_citation: ResolveCitationParams
  translate: TranslateParams
  render_bilingual: RenderBilingualParams
  glossary_lookup: GlossaryLookupParams
  glossary_add: GlossaryAddParams
  glossary_list: GlossaryListParams
  memory_search: MemorySearchParams
  memory_save: MemorySaveParams
  corpus_status: CorpusStatusParams
  corpus_tree: CorpusTreeParams
  doctor: DoctorParams
  regex_search: RegexSearchParams
  delete_document: DeleteDocumentParams
  cite_render: CiteRenderParams
  mempalace_search: MemPalaceSearchParams
  mempalace_wake_up: MemPalaceWakeUpParams
  mempalace_status: MemPalaceStatusParams
  mempalace_add: MemPalaceAddParams
  mempalace_instructions: MemPalaceInstructionsParams
  mempalace_compress: MemPalaceCompressParams
  cite_tree: CiteTreeParams
  writing_outline: WritingOutlineParams
  writing_draft: WritingDraftParams
  writing_style: WritingStyleParams
  writing_quality: WritingQualityParams
  passport_create: PassportCreateParams
  passport_load: PassportLoadParams
  passport_update: PassportUpdateParams
  passport_summary: PassportSummaryParams
  passport_list: PassportListParams
  graph_query: GraphQueryParams
  graph_stats: GraphStatsParams
  depth_measure: DepthMeasureParams
  devils_advocate: DevilsAdvocateParams
  review: ReviewParams
  diary_save: DiarySaveParams
  diary_load: DiaryLoadParams
  diary_list: DiaryListParams
  diary_recent: DiaryRecentParams
  code_subagent: CodeSubagentParams
  code_file_read: CodeFileReadParams
  code_file_write: CodeFileWriteParams
  code_file_edit: CodeFileEditParams
  code_file_list: CodeFileListParams
  code_bash: CodeBashParams
  code_grep: CodeGrepParams
  code_glob: CodeGlobParams
  compact_context: CompactContextParams
  permissions_check: PermissionsCheckParams
  permissions_list: PermissionsListParams
  permissions_set: PermissionsSetParams
}
