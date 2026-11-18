import { existsSync, mkdirSync, readFileSync, writeFileSync } from "fs"
import path from "path"
import type { Host } from "./hosts"

const skillTemplates: Record<string, string> = {
  "shutong-research": "---\nname: shutong-research\ndescription: Run citation-safe, paper-scoped research with Shutong.\n---\n\nUse this skill whenever the user asks to research, cite, ingest sources, or draft from the local corpus.\n\n1. Check `shutong_paper_status`. If no paper is active, ask whether to use the shared corpus or create/activate a paper; never silently choose a paper.\n2. Before ingestion, save a bibliography with `shutong_paper_set_bibliography` and ask for explicit approval using `shutong_paper_approve_bibliography`.\n3. For a paper, use only `shutong_search` with the active paper. Do not set `library_wide` unless the user explicitly asks.\n4. To add evidence, call `shutong_ingest`, add the returned `csl_id` with `shutong_paper_add_source`, then confirm it through `shutong_paper_mark_source_ingested`. Do not guess the role.\n5. Every note needs a locator and Verifier evidence: call `shutong_paper_add_note`, then `shutong_paper_verify_note`; claims need `shutong_paper_add_claim` and `shutong_paper_verify_claim`.\n6. Draft only after the scholar explicitly asks: call `shutong_paper_draft_context` with `draft_requested: true`, use only its verified claims, then export approved Markdown with `shutong_paper_export_docx`. If any gate is incomplete, report the missing evidence and ask the scholar for the next approval.\n7. Before relying on a source, call `shutong_verify`; exclude failed evidence. Cite every factual claim in Chicago author-date form.\n\nIf Shutong MCP tools are unavailable, explain that the project needs `shutong init` (or the host's local MCP setup) and do not fabricate corpus results.\n",
  "cite-research": "---\nname: cite-research\ndescription: Search the local corpus and verify every cited passage.\n---\n\nCall `shutong_search`, verify quoted passages with `shutong_verify`, exclude failures, and cite in Chicago author-date format.\n",
  "ingest-source": "---\nname: ingest-source\ndescription: Ingest a source into the local citation corpus.\n---\n\nBefore linking a paper source, obtain a scholar-selected `individual`, `batch`, or explicit `automatic` rule through `shutong_paper_authorize_ingestion`. Call `shutong_ingest`, then confirm the result with `shutong_search` and `shutong_paper_mark_source_ingested`.\n",
  "verify-corpus": "---\nname: verify-corpus\ndescription: Verify corpus Merkle integrity before relying on evidence.\n---\n\nCall `shutong_verify` with action `all` for a corpus audit, or action `node` with a `csl_id` for one document. Exclude failed evidence.\n",
  "corpus-status": "---\nname: corpus-status\ndescription: Inspect the local corpus document count, integrity health, and source tree.\n---\n\nCall `shutong_corpus_status`; call `shutong_corpus_tree` when document detail is needed.\n",
  "paper-workspace": "---\nname: paper-workspace\ndescription: Work inside a paper-scoped source set.\n---\n\nCreate or activate a paper with `shutong_paper_create` and `shutong_paper_use`. The required order is: approved bibliography, local ingestion, verified notes, then drafting. While a paper is active, use `shutong_search` only within its approved sources. Run `shutong_paper_audit` before drafting and stop on any missing stage.\n",
  "workspace-planner": "---\nname: workspace-planner\ndescription: Route a scholar's request to a confirmed project and work without mixing evidence.\n---\n\nUse this skill when a request may begin, resume, compare, or switch a paper, chapter, book, or research project. Call `shutong_workspace_plan_switch` with the new request and present its recommendation. Never switch automatically: call `shutong_workspace_activate` only after the scholar explicitly confirms the project and work.\n\nCreate a book with `shutong_workspace_create_project` using `kind: book`, then create each chapter with `shutong_workspace_create_work`. Book chapters share their project's bibliography and ingested sources, but retain separate notes, claims, audits, and drafts. For an article or independent paper, create a project and one `paper` work. Every specialist call must use the confirmed active work; never use notes or claims from another work without an explicit, re-verified transfer.\n",
  "explore-bibliography": "---\nname: explore-bibliography\ndescription: Build a paper-specific bibliography shortlist from public metadata.\n---\n\nUse `shutong_bibliography_search` only for public metadata, then return 30–50 directly relevant candidate works, label proposed primary/secondary roles and record provenance. Save with `shutong_paper_set_bibliography`; never ingest or draft until the scholar approves it. Use `shutong_paper_update_bibliography` only for scholar-requested contextual, opposing, or critical work. Record only publicly published professional contacts with `shutong_paper_record_public_contact`; `shutong_paper_draft_outreach` may draft but never send correspondence.\n",
  "noter": "---\nname: noter\ndescription: Create source-backed private working notes for an active paper.\n---\n\nAnswer paper questions from approved, ingested sources only. Search accumulated private material with `shutong_note` action `search`; results retain source IDs and locators. Use `shutong_paper_analyze_text_reuse` only as a review signal, never a plagiarism verdict. Create one reusable proposition per note; split when the source, locator, period, practice, language, or regional setting changes. Each new note needs an exact corpus locator, atomic claim, supporting evidence or tight paraphrase, confidence (`known`, `probable`, or `speculative`), and one or more tags; use `shutong_note` action `add`. After Verifier evidence, create claims only with `shutong_claim` action `add` from verified notes. If the source is missing or not ingested, explain the gap and ask the scholar to complete that step.\n",
  "verify-bibliography": "---\nname: verify-bibliography\ndescription: Independently verify bibliography and evidence before drafting.\n---\n\nVerify local citations, corpus integrity, notes, and claims. Record note checks with `shutong_paper_verify_note` and claim-evidence checks with `shutong_paper_verify_claim`. Report pass, fail, or uncertain with evidence and residual risk; never silently change an audited artifact.\n",
  "copyright-access": "---\nname: copyright-access\ndescription: Check lawful source availability before ingestion.\n---\n\nClassify a source as open, licensed, user-provided, metadata-only, restricted, or unavailable with `shutong_paper_set_source_access`. Only open, licensed, or user-provided sources can be marked ingested. Never bypass paywalls, access controls, CAPTCHA, terms, or rate limits.\n",
  "translate-academic": "---\nname: translate-academic\ndescription: Translate a scholarly passage with the original kept and citations preserved, then record it as a source-located evidence note.\n---\n\nUse when the scholar asks to translate a passage from an approved, ingested paper source; the output is a note, not prose.\n\n1. Confirm the active paper and that the source is approved and ingested. Never translate an unapproved or un-ingested source.\n2. Ask the scholar for the target language; default to Traditional Chinese (zh-Hant).\n3. Read `.shutong/glossary/*.json` first; glossary matches are mandatory; unmatched proper nouns become `[未译: OriginalTerm]`.\n4. Preserve citation keys and footnote markers exactly.\n5. Direct quotations: keep the original-language quotation verbatim and follow it with `（譯：……）`. Never replace the original with the translation.\n6. Bind each quotation to `source_id`, exact corpus locator, and a Chicago author-date reference rendered with `shutong_citation` action `render`; confirm with `shutong_verify` and check the exact match with `shutong_analysis` mode `quotation`.\n7. Create one proposition per note with `shutong_note` action `add`, with confidence (`known`, `probable`, or `speculative`) and tags including `translation` and the target language.\n8. Report notes written, glossary hits, `[未译]` terms, and any quotation whose original text did not match the corpus.\n",
}
const groupedSkillInstructions: Record<string, string> = {
  "shutong-research": "Use analysis-plan to scope work, then `shutong_search`, `shutong_analysis`, `shutong_verify` and grouped paper tools. Use evidence-synthesis for requested reports and short cited passages. Preserve the evidence gate; do not default to full-paper composition.",
  "ingest-source": "Use `shutong_source` for authorization and linking, then `shutong_ingest`.",
  "verify-corpus": "Use `shutong_verify` or `shutong_corpus` only.",
  "corpus-status": "Use `shutong_corpus` with action `status` or `tree`.",
  "paper-workspace": "Use `shutong_workspace`, `shutong_bibliography`, `shutong_source`, `shutong_note`, and `shutong_claim` actions.",
  "workspace-planner": "Use `shutong_workspace` with action `plan_switch` or `activate`; never activate without confirmation.",
  "explore-bibliography": "Use analysis-plan for source coverage and public metadata search, then `shutong_bibliography` actions. Do not ingest before approval.",
  "noter": "Use text-analysis and evidence-synthesis for passage analysis. Record analysis_id in `shutong_note` and use `shutong_claim` only after independent evidence review.",
  "verify-bibliography": "Use citation-check, `shutong_verify`, and `shutong_verifier_report` actions; review analysis results before verifying analysis-backed notes.",
  "copyright-access": "Use `shutong_source` with action `set_access` before ingestion.",
}
for (const [name, instruction] of Object.entries(groupedSkillInstructions)) {
  const frontmatter = skillTemplates[name].match(/^---\n[\s\S]*?\n---/)![0]
  skillTemplates[name] = `${frontmatter}\n\n${instruction}\n`
}
const analysisSkills = ["analysis-plan", "text-analysis", "evidence-synthesis", "citation-check"]
const commandTemplates: Record<string, string> = {
  research: "Search the local corpus for: $ARGUMENTS\n\nUse cite-research and verify every cited passage.\n",
  ingest: "Ingest this source: $ARGUMENTS\n\nUse ingest-source, then confirm searchability.\n",
  verify: "Verify this source or node hash: $ARGUMENTS\n\nUse verify-corpus.\n",
  corpus: "Use corpus-status.\n",
  paper: "Manage a paper workspace: $ARGUMENTS\n\nUse paper-workspace. Never use sources outside the active paper unless the user explicitly requests a library-wide search.\n",
}
function writeIfMissing(file: string, content: string, force: boolean, written: string[]) {
  if (!force && existsSync(file)) return
  mkdirSync(path.dirname(file), { recursive: true })
  writeFileSync(file, content, "utf8")
  written.push(file)
}
function pythonEnv() {
  return { SHUTONG_CORPUS_ROOT: "./corpus", SHUTONG_LIBRARY_ROOT: "./library", SHUTONG_GLOSSARY_DIR: "./.shutong/glossary" }
}
function mergeJson(file: string, key: string, value: Record<string, unknown>, force: boolean, written: string[]) {
  const current = existsSync(file) ? Bun.JSONC.parse(readFileSync(file, "utf8")) as Record<string, any> : {}
  current[key] ??= {}
  if (!force && current[key].shutong) return
  current[key].shutong = value.shutong
  mkdirSync(path.dirname(file), { recursive: true })
  writeFileSync(file, `${JSON.stringify(current, null, 2)}\n`, "utf8")
  written.push(file)
}
function renderCodexMcp(pythonBin: string) {
  const quote = (value: string) => JSON.stringify(value)
  return `\n[mcp_servers.shutong]\ncommand = ${quote(pythonBin)}\nargs = [${quote("-m")}, ${quote("shutong_backend.mcp_server")}]\n\n[mcp_servers.shutong.env]\nSHUTONG_CORPUS_ROOT = ${quote("./corpus")}\nSHUTONG_LIBRARY_ROOT = ${quote("./library")}\nSHUTONG_GLOSSARY_DIR = ${quote("./.shutong/glossary")}\n`
}

function renderHermesInstructions(pythonBin: string) {
  return `# Shutong MCP (local-only setup)\n\nShutong does not modify global Hermes settings. To enable this project, add the following to \`~/.hermes/config.yaml\` yourself:\n\n\`\`\`yaml\nmcp_servers:\n  shutong:\n    command: ${pythonBin}\n    args: ["-m", "shutong_backend.mcp_server"]\n    env:\n      SHUTONG_CORPUS_ROOT: ./corpus\n      SHUTONG_LIBRARY_ROOT: ./library\n      SHUTONG_GLOSSARY_DIR: ./.shutong/glossary\n\`\`\`\n`
}

export function renderHostArtifacts(host: Host, root: string, pythonBin: string, force = false): string[] {
  const written: string[] = []
  const templateRoot = [
    path.resolve(import.meta.dir, "../../python-backend/shutong_backend/templates/skills"),
    path.resolve(import.meta.dir, "../../../packages/shutong-backend/shutong_backend/templates/skills"),
  ].find((candidate) => existsSync(path.join(candidate, "text-analysis/SKILL.md")))
  if (!templateRoot) throw new Error("Shutong analysis skill templates are missing; rebuild or reinstall the package.")
  const templates = { ...skillTemplates }
  for (const name of analysisSkills) templates[name] = readFileSync(path.join(templateRoot, name, "SKILL.md"), "utf8")
  const skillRoot = host === "pi" ? ".pi/skills" : host === "codex" ? ".codex/skills" : ".agents/skills"
  for (const [name, content] of Object.entries(templates)) writeIfMissing(path.join(root, skillRoot, name, "SKILL.md"), content, force, written)
  if (host === "opencode" || host === "claude") {
    const commandRoot = host === "opencode" ? ".opencode/commands" : ".claude/commands"
    for (const [name, content] of Object.entries(commandTemplates)) writeIfMissing(path.join(root, commandRoot, `${name}.md`), content, force, written)
  }
  if (host === "claude") {
    writeIfMissing(path.join(root, "CLAUDE.md"), "# Shutong\n\nYou are Shutong, the primary scholar-workflow conductor. Read and follow `AGENTS.md` before acting.\n", force, written)
  }
  if (host === "opencode") {
    const jsonc = path.join(root, "opencode.jsonc")
    mergeJson(existsSync(jsonc) ? jsonc : path.join(root, "opencode.json"), "mcp", { shutong: { type: "local", command: [pythonBin, "-m", "shutong_backend.mcp_server"], environment: pythonEnv() } }, force, written)
  }
  if (host === "claude") mergeJson(path.join(root, ".mcp.json"), "mcpServers", { shutong: { command: pythonBin, args: ["-m", "shutong_backend.mcp_server"], env: pythonEnv() } }, force, written)
  if (host === "codex") {
    const file = path.join(root, ".codex", "config.toml")
    const current = existsSync(file) ? readFileSync(file, "utf8") : ""
    if (!current.includes("[mcp_servers.shutong]")) { mkdirSync(path.dirname(file), { recursive: true }); writeFileSync(file, `${current.trimEnd()}${renderCodexMcp(pythonBin)}`, "utf8"); written.push(file) }
  }
  if (host === "hermes") writeIfMissing(path.join(root, ".hermes", "SHUTONG-MCP.md"), renderHermesInstructions(pythonBin), force, written)
  return written
}
