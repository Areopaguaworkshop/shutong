import type { BackendMethod } from "./backend-types"

export interface ToolEntry {
  name: string
  method: BackendMethod
  description: string
  paramMap: (args: Record<string, unknown>) => Record<string, unknown>
}

const PUBLIC_TOOLS = [
  ["shutong_analysis", "Run and review paper-scoped text analysis with source provenance"],
  ["shutong_status", "Corpus health and research-state summary"],
  ["shutong_state_wake_up", "Load cross-session research context"],
  ["shutong_state_snapshot", "Inspect research state"],
  ["shutong_state_record_session", "Record a research session"],
  ["shutong_bibliography_search", "Search public scholarly metadata"],
  ["shutong_bibliography_source_catalog", "List scholarly source routes"],
  ["shutong_ingest", "Ingest an authorized source"],
  ["shutong_ingest_status", "Inspect ingestion progress"],
  ["shutong_delete_document", "Delete a corpus document"],
  ["shutong_search", "Search corpus by keyword or regex"],
  ["shutong_verify", "Verify a node or the complete corpus"],
  ["shutong_paper_audit", "Audit paper evidence gates"],
  ["shutong_paper_export_docx", "Export a gate-approved draft"],
  ["shutong_paper_status", "Inspect an active paper"],
  ["shutong_paper_use", "Activate a confirmed paper"],
  ["shutong_workspace", "Manage project and work actions"],
  ["shutong_bibliography", "Manage bibliography approval actions"],
  ["shutong_source", "Manage source access and ingestion actions"],
  ["shutong_corpus", "Inspect corpus state"],
  ["shutong_citation", "Resolve, render, or trace citations"],
  ["shutong_memory", "Manage local research memory"],
  ["shutong_outreach", "Record contacts or draft unsent outreach"],
  ["shutong_verifier_report", "Record or override verifier reports"],
] as const

const TOOLS: ToolEntry[] = PUBLIC_TOOLS.map(([name, description]) => ({
  name,
  description,
  method: "tool_call",
  paramMap: (arguments_) => ({ name, arguments: arguments_ }),
}))
const BY_NAME = new Map(TOOLS.map((tool) => [tool.name, tool]))

export function getTool(name: string): ToolEntry | undefined {
  return BY_NAME.get(name)
}

export function allTools(): ToolEntry[] {
  return TOOLS
}

export function resolveToolCall(name: string, args: Record<string, unknown>): { method: BackendMethod; params: Record<string, unknown> } {
  const tool = BY_NAME.get(name)
  if (!tool) throw new Error(`Unknown tool: ${name}`)
  return { method: tool.method, params: tool.paramMap(args) }
}
