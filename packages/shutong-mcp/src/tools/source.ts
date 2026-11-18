import { sourcePaper, writePaper } from "./paper-store.ts";
import { validatedIngestion } from "./audit.ts";
import { runtimeConfig } from "./context.ts";

const ACCESS = new Set(["open", "licensed", "user-provided", "metadata-only", "restricted", "unavailable"]);
const ROLES = new Set(["primary", "secondary", "unknown"]);

class SourceError extends Error {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

function bibliographyEntries(manifest: Record<string, any>): Array<Record<string, any>> {
  return Array.isArray(manifest.bibliography?.entries) ? manifest.bibliography.entries : [];
}

export async function handleSource(args: {
  action?: string;
  paper_id?: string;
  source_id?: string;
  category?: string;
  provenance?: string;
  mode?: string;
  source_ids?: string[];
  rule?: string;
  role?: string;
}): Promise<Record<string, unknown>> {
  try {
    if (!args.paper_id) {
      return { status: "error", error_code: "invalid_input", message: "paper_id is required." };
    }
    const { paper, sourceId, sourcePaper: manifest } = sourcePaper(args.paper_id);

    if (args.action === "set_access") {
      const category = args.category;
      if (!ACCESS.has(String(category))) {
        throw new SourceError(
          "invalid_access_category",
          "Access category must be open, licensed, user-provided, metadata-only, restricted, or unavailable.",
        );
      }
      const entry = bibliographyEntries(manifest).find((item) => item.id === args.source_id);
      if (!entry) {
        throw new SourceError("source_not_in_bibliography", "Record access only for a bibliography entry in this paper.");
      }
      entry.access = { category, provenance: String(args.provenance ?? "") };
      writePaper(sourceId, manifest);
      return { status: "ok", paper_id: paper.id, source_id: args.source_id, category };
    }

    if (args.action === "authorize") {
      const mode = args.mode;
      if (!["individual", "batch", "automatic"].includes(String(mode))) {
        throw new SourceError("invalid_ingestion_mode", "Ingestion mode must be individual, batch, or automatic.");
      }
      const sourceIds = Array.isArray(args.source_ids) ? args.source_ids : [];
      const bibliographyIds = new Set(bibliographyEntries(manifest).map((entry) => entry.id));
      if (
        (mode === "individual" || mode === "batch") &&
        (sourceIds.length === 0 || !sourceIds.every((id) => bibliographyIds.has(id)))
      ) {
        throw new SourceError(
          "invalid_ingestion_authorization",
          "Individual and batch authorization require bibliography source IDs.",
        );
      }
      const rule = String(args.rule ?? "").trim();
      if (mode === "automatic" && !rule) {
        throw new SourceError("missing_ingestion_rule", "Automatic ingestion requires a scholar-approved rule.");
      }
      manifest.ingestion = { mode, authorized_source_ids: sourceIds, rule };
      writePaper(sourceId, manifest);
      return { status: "ok", paper_id: paper.id, mode, authorized_source_ids: sourceIds };
    }

    if (args.action === "add") {
      const role = args.role ?? "unknown";
      if (!ROLES.has(role)) {
        throw new SourceError("invalid_source_role", "Source role must be primary, secondary, or unknown.");
      }
      if (manifest.bibliography?.status !== "approved") {
        throw new SourceError(
          "bibliography_not_approved",
          "Approve the bibliography before ingesting or adding a paper source.",
        );
      }
      const sourceIdValue = args.source_id;
      if (!bibliographyEntries(manifest).some((entry) => entry.id === sourceIdValue)) {
        throw new SourceError(
          "source_not_in_bibliography",
          "Add the source to the approved bibliography before assigning it to this paper.",
        );
      }
      const existing = (manifest.sources ?? []).find((item: any) => item.source_id === sourceIdValue);
      const ingested = existing?.ingested === true;
      manifest.sources = (manifest.sources ?? []).filter((item: any) => item.source_id !== sourceIdValue);
      manifest.sources.push({ source_id: sourceIdValue, role, ingested });
      writePaper(sourceId, manifest);
      return {
        status: "ok",
        paper_id: paper.id,
        source_workspace_id: sourceId,
        source_id: sourceIdValue,
        role,
        ingested,
      };
    }

    if (args.action === "mark_ingested") {
      const source = (manifest.sources ?? []).find((item: any) => item.source_id === args.source_id);
      if (!source) {
        throw new SourceError(
          "source_not_in_paper",
          "Add the approved bibliography source to the paper before marking it ingested.",
        );
      }
      const entry = bibliographyEntries(manifest).find((item) => item.id === args.source_id);
      if (!entry) {
        throw new SourceError(
          "source_not_in_bibliography",
          "Mark ingestion only for a source in the current approved bibliography.",
        );
      }
      const access = entry.access?.category;
      if (!["open", "licensed", "user-provided"].includes(access)) {
        throw new SourceError(
          "source_not_authorized",
          "Ingestion requires an open, licensed, or user-provided access record.",
        );
      }
      const authorization = manifest.ingestion ?? {};
      if (
        ["individual", "batch"].includes(authorization.mode) &&
        !(authorization.authorized_source_ids ?? []).includes(args.source_id)
      ) {
        throw new SourceError("source_not_authorized", "The scholar has not authorized ingestion for this source.");
      }
      if (!["individual", "batch", "automatic"].includes(authorization.mode)) {
        throw new SourceError(
          "ingestion_not_authorized",
          "Choose an individual, batch, or automatic ingestion authorization first.",
        );
      }
      validatedIngestion(runtimeConfig().corpusRoot, String(args.source_id));
      source.ingested = true;
      writePaper(sourceId, manifest);
      return { status: "ok", paper_id: paper.id, source_workspace_id: sourceId, source_id: args.source_id };
    }

    return {
      status: "error",
      error_code: "invalid_action",
      message: `Unknown source action: ${args.action ?? ""}`,
    };
  } catch (error) {
    const failure = error as SourceError;
    return {
      status: "error",
      error_code: failure.code ?? "source_error",
      message: failure.message,
    };
  }
}
