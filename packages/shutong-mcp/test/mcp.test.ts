import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync, chmodSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { Client } from "@modelcontextprotocol/client";
import { StdioClientTransport } from "@modelcontextprotocol/client/stdio";
import { buildMerkleTree, hashPayload } from "../src/contract/hash.ts";

function writeJson(file: string, value: unknown): void {
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, JSON.stringify(value, null, 2), "utf8");
}

function makeCorpus(): string {
  const root = mkdtempSync(path.join(os.tmpdir(), "shutong-mcp-"));
  for (const [folder, id, title, author, year, paragraphs] of [
    ["doc-a", "src-a", "中国经济发展", "袁", 2020, ["中国经济发展", "theology history"]],
    ["doc-b", "src-b", "Theology History", "Smith", 2021, ["theology history", "justification by faith"]],
  ] as const) {
    writeJson(path.join(root, folder, "csl.json"), {
      id,
      title,
      author: [{ family: author }],
      issued: { "date-parts": [[year]] },
      content_hash: `hash-${id}`,
    });
    writeJson(path.join(root, folder, "document.json"), {
      pages: [
        {
          page_number: 1,
          columns: [
            {
              paragraphs: paragraphs.map((text, index) => ({
                paragraph_id: `p1_${index + 1}`,
                text,
              })),
            },
          ],
        },
      ],
    });
    const leaves = paragraphs.map((text) => hashPayload(text));
    const tree = buildMerkleTree(leaves);
    writeJson(path.join(root, folder, "merkle.json"), tree);
  }

  const storage = path.join(root, ".shutong");
  writeJson(path.join(storage, "passport", "pp-12345678.json"), {
    passport_id: "pp-12345678",
    project_name: "Test Project",
    updated_at: "2026-01-02T00:00:00",
    research_goals: ["Test the state facade"],
    sources_consulted: ["src-a"],
    key_insights: [{ insight: "State reads are deterministic" }],
    open_questions: [{ question: "Does memory search work?", status: "open" }],
  });
  writeJson(path.join(storage, "diary", "2026-01-02.json"), [
    {
      entry_id: "diary-1",
      timestamp: "2026-01-02T00:00:00",
      session_id: "s1",
      topics_discussed: ["state", "memory"],
    },
  ]);
  writeJson(path.join(storage, "graph", "graph.json"), {
    nodes: [
      { node_id: "claim-1", node_type: "claim" },
      { node_id: "src-a", node_type: "source" },
    ],
    edges: [{ edge_id: "e1", source: "claim-1", target: "src-a", edge_type: "supports" }],
  });
  mkdirSync(path.join(root, ".memory"), { recursive: true });
  const memoryLine = `${JSON.stringify({
    entry_id: "mem-1",
    timestamp: "2026-01-02T00:00:00",
    thread_id: "default",
    query: "中国 经济",
    response: "memory response",
  })}\n`;
  writeFileSync(path.join(root, ".memory", "default.jsonl"), memoryLine, "utf8");
  mkdirSync(path.join(storage, "memory"), { recursive: true });
  writeFileSync(path.join(storage, "memory", "default.jsonl"), memoryLine, "utf8");
  writeJson(path.join(root, "papers", "test-paper", "paper.json"), {
    id: "test-paper",
    title: "Test Paper",
    question: "Does paper status work?",
    sources: [],
  });
  writeFileSync(path.join(storage, "active-paper"), "test-paper\n", "utf8");
  writeJson(path.join(root, "projects", "demo", "project.json"), {
    id: "demo",
    title: "Demo Project",
    kind: "book",
    source_workspace_id: "demo-sources",
    works: [],
  });
  writeJson(path.join(storage, "active-workspace.json"), {
    project_id: "demo",
    work_id: "demo-work",
  });
  writeJson(path.join(storage, "ingestion-status.json"), {
    status: "ok",
    stage: "done",
    document_path: "doc-a",
  });
  writeJson(path.join(storage, "source-registry.json"), {
    "src-a": { document_path: "doc-a" },
  });
  const notePath = path.join(root, "papers", "audit-paper", "notes", "note-1.md");
  mkdirSync(path.dirname(notePath), { recursive: true });
  writeFileSync(
    notePath,
    "---\n" +
      "source_id: src-a\n" +
      "locator: p1\n" +
      "claim: A verified claim\n" +
      "evidence: test evidence\n" +
      "confidence: known\n" +
      "tags: [test]\n" +
      "verified: true\n" +
      "verifier_report_id: report-1\n" +
      "---\nVerified body.\n",
    "utf8",
  );
  const digest = createHash("sha256").update(readFileSync(notePath)).digest("hex");
  writeJson(path.join(root, "papers", "audit-paper", "paper.json"), {
    id: "audit-paper",
    title: "Audit Paper",
    sources: [{ source_id: "src-a", role: "primary", ingested: true }],
    bibliography: { status: "approved", entries: [{ id: "src-a", title: "中国经济发展" }] },
    policy: { minimum_primary: 1, minimum_secondary: 0 },
  });
  writeJson(path.join(root, "papers", "audit-paper", "audits", "report-1.json"), {
    report_id: "report-1",
    outcome: "pass",
    scope: "paper",
  });
  writeJson(path.join(root, "papers", "audit-paper", "audits", "report-2.json"), {
    report_id: "report-2",
    outcome: "pass",
    scope: "paper",
  });
  writeJson(path.join(root, "papers", "audit-paper", "claims", "claim-1.json"), {
    id: "claim-1",
    text: "A verified claim",
    note_ids: ["note-1"],
    note_digests: { "note-1": digest },
    verified: true,
    verifier_report_id: "report-2",
  });
  return root;
}

function parseContent(result: { content: unknown }): any {
  const content = Array.isArray(result.content) ? result.content : [];
  const text = content.find((block: any) => block?.type === "text")?.text;
  return JSON.parse(String(text));
}

function readJson(file: string): any {
  return JSON.parse(readFileSync(file, "utf8"));
}

test("MCP server lists tools and serves the read-only slice", async () => {
  const corpus = makeCorpus();
  const fakeCiteindex = path.join(corpus, "fake-citeindex.cjs");
  writeFileSync(
    fakeCiteindex,
    `#!/usr/bin/env node
const fs = require("node:fs");
const path = require("node:path");
const args = process.argv.slice(2);
const corpus = args[args.indexOf("--corpus-root") + 1];
const dir = path.join(corpus, "ingest-fixture");
fs.mkdirSync(dir, { recursive: true });
fs.writeFileSync(path.join(dir, "csl.json"), JSON.stringify({ id: "src-ingest", title: "Ingested" }));
fs.writeFileSync(path.join(dir, "document.json"), JSON.stringify({ pages: [] }));
fs.writeFileSync(path.join(dir, "merkle.json"), JSON.stringify({ root: "ingest-root", levels: [["ingest-root"]] }));
process.stdout.write(JSON.stringify({ status: "ok", document_path: dir, standardized_csl_json: { id: "src-ingest", merkle_root: "ingest-root" }, sub_pipeline_outputs: { document_json: { nodes: [{ text: "ingested text" }] } } }) + "\\n");
`,
    "utf8",
  );
  chmodSync(fakeCiteindex, 0o755);
  const env = {
    ...process.env,
    SHUTONG_CORPUS_ROOT: corpus,
    SHUTONG_STORAGE_DIR: path.join(corpus, ".shutong"),
    SHUTONG_INDEX_DB: path.join(corpus, ".shutong", "search.sqlite"),
    SHUTONG_CITEINDEX_BIN: fakeCiteindex,
    SHUTONG_PYTHON: path.resolve(
      import.meta.dirname,
      "../../shutong-backend/.venv/bin/python",
    ),
  };
  const transport = new StdioClientTransport({
    command: process.execPath,
    args: [path.resolve(import.meta.dirname, "../src/index.ts")],
    env,
    cwd: corpus,
    stderr: "pipe",
  });
  const client = new Client({ name: "shutong-test", version: "1.0.0" });
  try {
    await client.connect(transport);
    const listed = await client.listTools();
    assert.deepEqual(
      listed.tools.map((tool) => tool.name).sort(),
      [
        "shutong_analysis",
        "shutong_bibliography",
        "shutong_bibliography_search",
        "shutong_bibliography_source_catalog",
        "shutong_citation",
        "shutong_claim",
        "shutong_corpus",
        "shutong_delete_document",
        "shutong_ingest",
        "shutong_ingest_status",
        "shutong_memory",
        "shutong_note",
        "shutong_outreach",
        "shutong_paper_audit",
        "shutong_paper_export_docx",
        "shutong_paper_status",
        "shutong_paper_use",
        "shutong_search",
        "shutong_source",
        "shutong_state_record_session",
        "shutong_state_snapshot",
        "shutong_state_wake_up",
        "shutong_status",
        "shutong_verifier_report",
        "shutong_verify",
        "shutong_workspace",
      ],
    );

    const status = parseContent(
      await client.callTool({ name: "shutong_corpus", arguments: { action: "status" } }),
    );
    assert.equal(status.status, "ok");
    assert.equal(status.document_count, 2);

    const search = parseContent(
      await client.callTool({
        name: "shutong_search",
        arguments: { query: "中国", mode: "keyword", top_k: 5 },
      }),
    );
    assert.equal(search.status, "ok");
    assert.ok(search.results.length > 0);
    assert.equal(search.results[0].source_id, "src-a");

    const regex = parseContent(
      await client.callTool({
        name: "shutong_search",
        arguments: { pattern: "经济", mode: "regex", top_k: 5 },
      }),
    );
    assert.equal(regex.status, "ok");
    assert.equal(regex.results[0].source_id, "src-a");

    const treeView = parseContent(
      await client.callTool({ name: "shutong_corpus", arguments: { action: "tree" } }),
    );
    assert.equal(treeView.status, "ok");
    assert.equal(treeView.documents.length, 2);

    const verify = parseContent(
      await client.callTool({
        name: "shutong_verify",
        arguments: { csl_id: "src-a", mode: "node" },
      }),
    );
    assert.equal(verify.status, "pass", JSON.stringify(verify));

    const verifyAll = parseContent(
      await client.callTool({ name: "shutong_verify", arguments: { mode: "all" } }),
    );
    assert.equal(verifyAll.status, "ok", JSON.stringify(verifyAll));
    assert.equal(verifyAll.failures, 0);

    const snapshot = parseContent(
      await client.callTool({ name: "shutong_state_snapshot", arguments: {} }),
    );
    assert.equal(snapshot.passports.length, 1);
    assert.equal(snapshot.graph.nodes, 2);
    assert.deepEqual(snapshot.diary_dates, ["2026-01-02"]);
    assert.equal(snapshot.memory_threads.length, 1);

    const wake = parseContent(
      await client.callTool({ name: "shutong_state_wake_up", arguments: { max_tokens: 500 } }),
    );
    assert.match(wake.context, /Project: Test Project/);
    assert.match(wake.context, /## Recent sessions/);

    const memorySearch = parseContent(
      await client.callTool({
        name: "shutong_memory",
        arguments: { action: "search", query: "中国" },
      }),
    );
    assert.equal(memorySearch.status, "ok");
    assert.equal(memorySearch.results.length, 1);

    const memoryList = parseContent(
      await client.callTool({ name: "shutong_memory", arguments: { action: "list" } }),
    );
    assert.equal(memoryList.status, "ok");
    assert.equal(memoryList.threads[0].thread_id, "default");

    const paper = parseContent(
      await client.callTool({ name: "shutong_paper_status", arguments: {} }),
    );
    assert.equal(paper.status, "ok");
    assert.equal(paper.paper.id, "test-paper");
    assert.equal(paper.active, true);

    const audit = parseContent(
      await client.callTool({ name: "shutong_paper_audit", arguments: {} }),
    );
    assert.equal(audit.status, "incomplete");
    assert.ok(audit.missing.some((item: any) => item.stage === "bibliography"));
    assert.ok(audit.missing.some((item: any) => item.stage === "notes"));
    assert.ok(audit.missing.some((item: any) => item.stage === "claims"));

    const validAudit = parseContent(
      await client.callTool({
        name: "shutong_paper_audit",
        arguments: { paper_id: "audit-paper" },
      }),
    );
    assert.equal(validAudit.status, "ok", JSON.stringify(validAudit));
    assert.deepEqual(validAudit.missing, []);

    const overallStatus = parseContent(
      await client.callTool({ name: "shutong_status", arguments: {} }),
    );
    assert.equal(overallStatus.corpus.document_count, 2);
    assert.equal(overallStatus.integrity.documents_checked, 2);
    assert.equal(overallStatus.integrity.failures, 0);
    assert.equal(overallStatus.research_state.passports.length, 1);

    const catalog = parseContent(
      await client.callTool({ name: "shutong_bibliography_source_catalog", arguments: {} }),
    );
    assert.equal(catalog.status, "ok");
    assert.ok(catalog.sources.length >= 5);

    const bibliography = parseContent(
      await client.callTool({
        name: "shutong_bibliography_search",
        arguments: { query: "test", sources: ["unsupported"] },
      }),
    );
    assert.equal(bibliography.status, "ok");
    assert.equal(bibliography.entries.length, 0);
    assert.equal(bibliography.errors[0].source, "unsupported");

    const workspaces = parseContent(
      await client.callTool({ name: "shutong_workspace", arguments: { action: "list" } }),
    );
    assert.equal(workspaces.status, "ok");
    assert.equal(workspaces.projects.length, 1);
    assert.equal(workspaces.projects[0].id, "demo");
    assert.equal(workspaces.active.project_id, "demo");

    const createdProject = parseContent(
      await client.callTool({
        name: "shutong_workspace",
        arguments: { action: "create_project", project_id: "new-project", title: "New Project", kind: "book" },
      }),
    );
    assert.equal(createdProject.status, "ok");
    assert.ok(existsSync(path.join(corpus, "projects", "new-project", "project.json")));
    assert.ok(existsSync(path.join(corpus, "papers", "new-project-sources", "paper.json")));

    const createdWork = parseContent(
      await client.callTool({
        name: "shutong_workspace",
        arguments: {
          action: "create_work",
          project_id: "new-project",
          work_id: "chapter-1",
          title: "Chapter One",
        },
      }),
    );
    assert.equal(createdWork.status, "ok");
    assert.ok(existsSync(path.join(corpus, "papers", "chapter-1", "paper.json")));

    const activated = parseContent(
      await client.callTool({
        name: "shutong_workspace",
        arguments: {
          action: "activate",
          project_id: "new-project",
          work_id: "chapter-1",
          confirmed: true,
        },
      }),
    );
    assert.equal(activated.status, "ok");
    assert.equal(readJson(path.join(corpus, ".shutong", "active-workspace.json")).work_id, "chapter-1");

    const savedMemory = parseContent(
      await client.callTool({
        name: "shutong_memory",
        arguments: { action: "save", title: "Test memory", content: "Saved through MCP" },
      }),
    );
    assert.equal(savedMemory.status, "ok");
    assert.ok(existsSync(path.join(corpus, ".memory", "notes.jsonl")));

    const writePaper = parseContent(
      await client.callTool({
        name: "shutong_workspace",
        arguments: { action: "create_paper", paper_id: "write-paper", title: "Write Paper" },
      }),
    );
    assert.equal(writePaper.status, "ok");

    const setBibliography = parseContent(
      await client.callTool({
        name: "shutong_bibliography",
        arguments: {
          action: "set",
          paper_id: "write-paper",
          entries: [{ id: "src-a", title: "中国经济发展", role: "primary" }],
        },
      }),
    );
    assert.equal(setBibliography.status, "needs_approval");

    const setAccess = parseContent(
      await client.callTool({
        name: "shutong_source",
        arguments: {
          action: "set_access",
          paper_id: "write-paper",
          source_id: "src-a",
          category: "open",
        },
      }),
    );
    assert.equal(setAccess.status, "ok");

    const approve = parseContent(
      await client.callTool({
        name: "shutong_bibliography",
        arguments: { action: "approve", paper_id: "write-paper", decision: "approve" },
      }),
    );
    assert.equal(approve.status, "ok");

    const authorize = parseContent(
      await client.callTool({
        name: "shutong_source",
        arguments: {
          action: "authorize",
          paper_id: "write-paper",
          mode: "individual",
          source_ids: ["src-a"],
        },
      }),
    );
    assert.equal(authorize.status, "ok");

    const addSource = parseContent(
      await client.callTool({
        name: "shutong_source",
        arguments: {
          action: "add",
          paper_id: "write-paper",
          source_id: "src-a",
          role: "primary",
        },
      }),
    );
    assert.equal(addSource.status, "ok");

    const markIngested = parseContent(
      await client.callTool({
        name: "shutong_source",
        arguments: { action: "mark_ingested", paper_id: "write-paper", source_id: "src-a" },
      }),
    );
    assert.equal(markIngested.status, "ok");
    assert.equal(
      readJson(path.join(corpus, "papers", "write-paper", "paper.json")).sources[0].ingested,
      true,
    );

    const imported = parseContent(
      await client.callTool({
        name: "shutong_bibliography",
        arguments: {
          action: "import",
          paper_id: "write-paper",
          format: "bibtex",
          content: "@article{src-a, title={Test}}",
        },
      }),
    );
    assert.equal(imported.status, "ok");
    assert.ok(existsSync(path.join(corpus, "papers", "write-paper", "imports", "bibliography.bib")));

    const contact = parseContent(
      await client.callTool({
        name: "shutong_outreach",
        arguments: {
          action: "record_contact",
          paper_id: "write-paper",
          name: "Scholar",
          provenance: "https://example.org/contact",
        },
      }),
    );
    assert.equal(contact.status, "ok");
    assert.equal(contact.contact_id, "contact-1");

    const draft = parseContent(
      await client.callTool({
        name: "shutong_outreach",
        arguments: {
          action: "draft",
          paper_id: "write-paper",
          contact_id: "contact-1",
          body: "A draft for scholar review.",
        },
      }),
    );
    assert.equal(draft.status, "drafted_not_sent");
    assert.ok(existsSync(path.join(corpus, "papers", "write-paper", "contacts", "contact-1-outreach.md")));

    const report = parseContent(
      await client.callTool({
        name: "shutong_verifier_report",
        arguments: {
          action: "record",
          paper_id: "write-paper",
          outcome: "fail",
          report_id: "verifier-test",
          evidence: "test evidence",
        },
      }),
    );
    assert.equal(report.status, "ok");

    const override = parseContent(
      await client.callTool({
        name: "shutong_verifier_report",
        arguments: {
          action: "override",
          paper_id: "write-paper",
          report_id: "verifier-test",
          reason: "Scholar reviewed the residual risk.",
        },
      }),
    );
    assert.equal(override.status, "ok");
    assert.ok(existsSync(path.join(corpus, "papers", "write-paper", "audits", "overrides.jsonl")));

    const passReport = parseContent(
      await client.callTool({
        name: "shutong_verifier_report",
        arguments: {
          action: "record",
          paper_id: "write-paper",
          outcome: "pass",
          report_id: "verifier-pass",
          evidence: "Passing evidence",
        },
      }),
    );
    assert.equal(passReport.status, "ok");

    const addedNote = parseContent(
      await client.callTool({
        name: "shutong_note",
        arguments: {
          action: "add",
          paper_id: "write-paper",
          source_id: "src-a",
          locator: "p1",
          claim: "A note claim",
          evidence: "A note evidence",
          confidence: "known",
          tags: ["test"],
        },
      }),
    );
    assert.equal(addedNote.status, "ok");
    assert.equal(addedNote.note_id, "note-1");

    const verifiedNote = parseContent(
      await client.callTool({
        name: "shutong_note",
        arguments: {
          action: "verify",
          paper_id: "write-paper",
          note_id: "note-1",
          evidence: "Verifier checked the note",
          verifier_report_id: "verifier-pass",
        },
      }),
    );
    assert.equal(verifiedNote.status, "ok");
    const noteText = readFileSync(path.join(corpus, "papers", "write-paper", "notes", "note-1.md"), "utf8");
    assert.match(noteText, /verified: true/);
    assert.match(noteText, /verifier_report_id: verifier-pass/);

    const searchedNotes = parseContent(
      await client.callTool({
        name: "shutong_note",
        arguments: { action: "search", paper_id: "write-paper", query: "note claim" },
      }),
    );
    assert.equal(searchedNotes.status, "ok");
    assert.equal(searchedNotes.matches[0].note_id, "note-1");

    const addedClaim = parseContent(
      await client.callTool({
        name: "shutong_claim",
        arguments: {
          action: "add",
          paper_id: "write-paper",
          text: "A claim from note-1",
          note_ids: ["note-1"],
        },
      }),
    );
    assert.equal(addedClaim.status, "ok");
    assert.equal(addedClaim.claim_id, "claim-1");

    const verifiedClaim = parseContent(
      await client.callTool({
        name: "shutong_claim",
        arguments: {
          action: "verify",
          paper_id: "write-paper",
          claim_id: "claim-1",
          evidence: "Verifier checked the claim",
          verifier_report_id: "verifier-pass",
        },
      }),
    );
    assert.equal(verifiedClaim.status, "ok");
    assert.equal(readJson(path.join(corpus, "papers", "write-paper", "claims", "claim-1.json")).verified, true);

    const exported = parseContent(
      await client.callTool({
        name: "shutong_paper_export_docx",
        arguments: {
          paper_id: "audit-paper",
          draft_requested: true,
          draft: "# Draft\n\nA verified claim.",
          filename: "draft",
        },
      }),
    );
    assert.equal(exported.status, "ok", JSON.stringify(exported));
    const docxPath = path.join(corpus, "papers", "audit-paper", "drafts", "draft.docx");
    assert.ok(existsSync(docxPath));
    assert.equal(readFileSync(docxPath).subarray(0, 2).toString(), "PK");

    const analysis = parseContent(
      await client.callTool({
        name: "shutong_analysis",
        arguments: {
          action: "run",
          paper_id: "audit-paper",
          mode: "concordance",
          language: "zh",
          question: "Where is the economy discussed?",
          source_ids: ["src-a"],
          query: "经济",
          limit: 5,
        },
      }),
    );
    assert.equal(analysis.status, "ok", JSON.stringify(analysis));
    assert.ok(analysis.analysis.results.contexts.length > 0);

    const fetchedAnalysis = parseContent(
      await client.callTool({
        name: "shutong_analysis",
        arguments: {
          action: "get",
          paper_id: "audit-paper",
          analysis_id: analysis.analysis.analysis_id,
        },
      }),
    );
    assert.equal(fetchedAnalysis.status, "ok");

    const reviewedAnalysis = parseContent(
      await client.callTool({
        name: "shutong_analysis",
        arguments: {
          action: "review",
          paper_id: "audit-paper",
          analysis_id: analysis.analysis.analysis_id,
          record_sha256: fetchedAnalysis.record_sha256,
          outcome: "pass",
          evidence: "Reviewed the concordance.",
          reviewer: "tester",
        },
      }),
    );
    assert.equal(reviewedAnalysis.status, "ok");

    const ingested = parseContent(
      await client.callTool({
        name: "shutong_ingest",
        arguments: { source: "https://example.org/article", is_primary: true },
      }),
    );
    assert.equal(ingested.status, "ok", JSON.stringify(ingested));
    assert.equal(ingested.csl_id, "src-ingest");
    assert.equal(ingested.node_count, 1);

    const ingestionStatus = parseContent(
      await client.callTool({ name: "shutong_ingest_status", arguments: {} }),
    );
    assert.equal(ingestionStatus.status, "ok");
    assert.equal(ingestionStatus.csl_id, "src-ingest");
    assert.equal(readJson(path.join(corpus, ".shutong", "source-registry.json"))["src-ingest"].merkle_root, "ingest-root");

    writeJson(path.join(corpus, "doc-delete", "csl.json"), { id: "src-delete", title: "Delete Me" });
    writeJson(path.join(corpus, "doc-delete", "document.json"), { pages: [] });
    writeJson(path.join(corpus, "doc-delete", "merkle.json"), {
      algorithm: "sha256",
      leaf_count: 1,
      levels: [[
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      ]],
      root: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    });
    const registryPath = path.join(corpus, ".shutong", "source-registry.json");
    const registry = readJson(registryPath);
    registry["src-delete"] = { document_path: "doc-delete" };
    writeJson(registryPath, registry);

    const deleted = parseContent(
      await client.callTool({
        name: "shutong_delete_document",
        arguments: { csl_id: "src-delete" },
      }),
    );
    assert.equal(deleted.status, "ok");
    assert.equal(existsSync(path.join(corpus, "doc-delete")), false);
    assert.equal(readJson(registryPath)["src-delete"], undefined);

    const used = parseContent(
      await client.callTool({
        name: "shutong_paper_use",
        arguments: { paper_id: "audit-paper" },
      }),
    );
    assert.equal(used.status, "ok");
    assert.equal(readFileSync(path.join(corpus, ".shutong", "active-paper"), "utf8").trim(), "audit-paper");

    const recorded = parseContent(
      await client.callTool({
        name: "shutong_state_record_session",
        arguments: {
          session_id: "session-2",
          topics: ["state", "writes"],
          insights: ["Session writes work"],
          passport_id: "pp-12345678",
        },
      }),
    );
    assert.ok(recorded.diary_entry_id);
    assert.equal(recorded.passport_updated, "pp-12345678");
    const diaryDir = path.join(corpus, ".shutong", "diary");
    assert.ok(
      readdirSync(diaryDir).some((file) => {
        const entries = readJson(path.join(diaryDir, file));
        return Array.isArray(entries) && entries.some((entry: any) => entry.session_id === "session-2");
      }),
    );

    const resolve = parseContent(
      await client.callTool({
        name: "shutong_citation",
        arguments: { action: "resolve", citation_key: "袁 2020" },
      }),
    );
    assert.equal(resolve.status, "ok");
    assert.equal(resolve.source_id, "src-a");

    const render = parseContent(
      await client.callTool({
        name: "shutong_citation",
        arguments: { action: "render", csl_id: "src-a" },
      }),
    );
    assert.equal(render.status, "ok");
    assert.match(render.bibliography, /袁/);
    assert.match(render.in_text, /袁 2020/);
    assert.equal(render.engine, "ts-native-chicago");

    const tree = parseContent(
      await client.callTool({
        name: "shutong_citation",
        arguments: { action: "tree", csl_id: "src-a" },
      }),
    );
    assert.equal(tree.status, "ok");
    assert.equal(tree.tree.root, readJson(path.join(corpus, "doc-a", "merkle.json")).root);
  } finally {
    await client.close();
    rmSync(corpus, { recursive: true, force: true });
  }
});
