import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { paperDir, readPaper } from "./paper-store.ts";
import { nextId } from "./ids.ts";

const ID_RE = /^[a-z0-9][a-z0-9-]{0,62}$/;

class OutreachError extends Error {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

export async function handleOutreach(args: {
  action?: string;
  paper_id?: string;
  name?: string;
  email?: string;
  affiliation?: string;
  related_work?: string;
  provenance?: string;
  contact_id?: string;
  body?: string;
}): Promise<Record<string, unknown>> {
  try {
    if (!args.paper_id) {
      return { status: "error", error_code: "invalid_input", message: "paper_id is required." };
    }
    readPaper(args.paper_id);
    const contacts = path.join(paperDir(args.paper_id), "contacts");

    if (args.action === "record_contact") {
      const name = String(args.name ?? "").trim();
      const provenance = String(args.provenance ?? "").trim();
      if (!name || !provenance) {
        throw new OutreachError(
          "missing_contact_provenance",
          "Public contacts require a name and the public page where the contact was published.",
        );
      }
      const contactId = args.contact_id ?? nextId(contacts, "contact-", ".json");
      if (!ID_RE.test(contactId)) {
        throw new OutreachError("invalid_contact_id", "Contact IDs use lowercase letters, numbers, and hyphens.");
      }
      const contact = {
        id: contactId,
        name,
        email: String(args.email ?? ""),
        affiliation: String(args.affiliation ?? ""),
        related_work: String(args.related_work ?? ""),
        provenance,
      };
      mkdirSync(contacts, { recursive: true });
      writeFileSync(path.join(contacts, `${contactId}.json`), `${JSON.stringify(contact, null, 2)}\n`, "utf8");
      return { status: "ok", paper_id: args.paper_id, contact_id: contactId };
    }

    if (args.action === "draft") {
      const contactId = String(args.contact_id ?? "");
      if (!ID_RE.test(contactId)) {
        throw new OutreachError("invalid_contact_id", "Contact IDs use lowercase letters, numbers, and hyphens.");
      }
      const contactPath = path.resolve(contacts, `${contactId}.json`);
      const relative = path.relative(path.resolve(contacts), contactPath);
      if (relative.startsWith("..") || path.isAbsolute(relative)) {
        throw new OutreachError("invalid_contact_id", "Contact paths must stay inside the paper contacts directory.");
      }
      if (!existsSync(contactPath)) {
        throw new OutreachError("contact_not_found", `Contact not found: ${contactId}`);
      }
      const body = String(args.body ?? "").trim();
      if (!body) {
        throw new OutreachError("empty_outreach_draft", "Outreach drafts require a message body for scholar review.");
      }
      const draftPath = path.join(contacts, `${contactId}-outreach.md`);
      writeFileSync(draftPath, `# Unsent outreach draft\n\nContact: ${contactId}\n\n${body}\n`, "utf8");
      return { status: "drafted_not_sent", paper_id: args.paper_id, path: draftPath };
    }

    return {
      status: "error",
      error_code: "invalid_action",
      message: `Unknown outreach action: ${args.action ?? ""}`,
    };
  } catch (error) {
    const failure = error as OutreachError;
    return {
      status: "error",
      error_code: failure.code ?? "outreach_error",
      message: failure.message,
    };
  }
}
