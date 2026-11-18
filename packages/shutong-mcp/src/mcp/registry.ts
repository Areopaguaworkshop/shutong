import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fromJsonSchema, McpServer, type JsonSchemaType } from "@modelcontextprotocol/server";
import { handleCitation } from "../tools/citation.ts";
import { handleAnalysis } from "../tools/analysis.ts";
import { handleBibliography } from "../tools/bibliography.ts";
import { handleBibliographyGroup } from "../tools/bibliography-writes.ts";
import { handleClaim } from "../tools/claim.ts";
import { handleCorpus } from "../tools/corpus.ts";
import { handleMemory } from "../tools/memory.ts";
import { handleNote } from "../tools/note.ts";
import { handlePaperAudit } from "../tools/audit.ts";
import { handleExportDocx } from "../tools/docx.ts";
import { handleOutreach } from "../tools/outreach.ts";
import { handleSearch } from "../tools/search.ts";
import { handleSource } from "../tools/source.ts";
import { handleIngestStatus, handleDeleteDocument } from "../tools/ingest.ts";
import { handleIngest } from "../tools/ingest-adapter.ts";
import { handleVerifierReport } from "../tools/verifier-report.ts";
import { handleStateSnapshot, handleStateWakeUp, handleStateRecordSession } from "../tools/state.ts";
import { handlePaperStatus, handlePaperUse, handleStatus } from "../tools/status.ts";
import { handleVerify } from "../tools/verify.ts";
import { handleWorkspace } from "../tools/workspace.ts";
import { VERSION } from "../version.ts";

interface ToolDefinition {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}

const definitionFile = [
  path.join(import.meta.dirname, "../tools.generated.json"),
  path.join(import.meta.dirname, "../../tools.generated.json"),
].find((candidate) => existsSync(candidate));
if (!definitionFile) throw new Error("tools.generated.json is missing from the package.");
const definitions = JSON.parse(readFileSync(definitionFile, "utf8")) as ToolDefinition[];

/** The first read-only vertical slice. */
export const IMPLEMENTED_TOOLS = new Set([
  "shutong_search",
  "shutong_verify",
  "shutong_corpus",
  "shutong_citation",
  "shutong_state_wake_up",
  "shutong_state_snapshot",
  "shutong_memory",
  "shutong_status",
  "shutong_paper_status",
  "shutong_paper_audit",
  "shutong_bibliography_search",
  "shutong_bibliography_source_catalog",
  "shutong_workspace",
  "shutong_bibliography",
  "shutong_source",
  "shutong_outreach",
  "shutong_verifier_report",
  "shutong_ingest_status",
  "shutong_delete_document",
  "shutong_paper_use",
  "shutong_state_record_session",
  "shutong_note",
  "shutong_claim",
  "shutong_paper_export_docx",
  "shutong_analysis",
  "shutong_ingest",
]);

type ToolResult = {
  content: Array<{ type: "text"; text: string }>;
  isError?: boolean;
};

async function dispatch(name: string, args: Record<string, unknown>): Promise<unknown> {
  switch (name) {
    case "shutong_search":
      return handleSearch(args);
    case "shutong_verify":
      return handleVerify(args);
    case "shutong_corpus":
      return handleCorpus(args);
    case "shutong_citation":
      return handleCitation(args);
    case "shutong_state_wake_up":
      return handleStateWakeUp(args);
    case "shutong_state_snapshot":
      return handleStateSnapshot();
    case "shutong_memory":
      return handleMemory(args);
    case "shutong_status":
      return handleStatus();
    case "shutong_paper_status":
      return handlePaperStatus(args);
    case "shutong_paper_audit":
      return handlePaperAudit(args);
    case "shutong_bibliography_search":
      return handleBibliography({ ...args, action: "search" });
    case "shutong_bibliography_source_catalog":
      return handleBibliography({ action: "source_catalog" });
    case "shutong_workspace":
      return handleWorkspace(args);
    case "shutong_bibliography":
      return handleBibliographyGroup(args);
    case "shutong_source":
      return handleSource(args);
    case "shutong_outreach":
      return handleOutreach(args);
    case "shutong_verifier_report":
      return handleVerifierReport(args);
    case "shutong_ingest_status":
      return handleIngestStatus();
    case "shutong_delete_document":
      return handleDeleteDocument(args);
    case "shutong_paper_use":
      return handlePaperUse(args);
    case "shutong_state_record_session":
      return handleStateRecordSession(args);
    case "shutong_note":
      return handleNote(args);
    case "shutong_claim":
      return handleClaim(args);
    case "shutong_paper_export_docx":
      return handleExportDocx(args);
    case "shutong_analysis":
      return handleAnalysis(args as Record<string, any>);
    case "shutong_ingest":
      return handleIngest(args);
    default:
      return {
        status: "error",
        error_code: "not_implemented",
        message: `${name} is not implemented in this read-only slice.`,
      };
  }
}

function toResult(payload: unknown): ToolResult {
  const status = (payload as { status?: string } | null)?.status;
  return {
    content: [{ type: "text", text: JSON.stringify(payload) }],
    isError: status === "error",
  };
}

export function createServer(): McpServer {
  const server = new McpServer({ name: "shutong", version: VERSION });
  for (const definition of definitions) {
    if (!IMPLEMENTED_TOOLS.has(definition.name)) continue;
    server.registerTool(
      definition.name,
      {
        description: definition.description,
        inputSchema: fromJsonSchema(definition.inputSchema as JsonSchemaType),
      },
      async (args: unknown) => {
        try {
          return toResult(await dispatch(definition.name, (args ?? {}) as Record<string, unknown>));
        } catch (error) {
          return {
            content: [
              {
                type: "text",
                text: JSON.stringify({
                  status: "error",
                  error_code: "internal_error",
                  message: (error as Error).message,
                }),
              },
            ],
            isError: true,
          };
        }
      },
    );
  }
  return server;
}
