# Paper-scoped scholar agent — implementation plan

## Goal

Ship `shutong` as an npm package for Codex, OpenCode, and Claude Code. Each local project hosts one or more **single-scholar, paper-scoped** workspaces. Shutong coordinates Bibliographer, Ingestor, Noter, and Verifier; it never substitutes for the scholar's approval or authorship.

This plan implements the decisions in [the 2026-08-29 architecture brief](../archetecture-2026-08-29.md). It deliberately starts with bibliography, evidence, and audit artifacts—not a broad autonomous writing swarm.

## Constraints

- A Workspace Planner resolves each request to a scholar-confirmed project and work before any specialist runs. It may recommend a switch but never activates another workspace silently.
- A book project owns one shared bibliography and ingested-source library. Its chapters are separate works with their own notes, claims, audits, and drafts.
- Paper files, source files, notes, locally stored contacts, and research state stay local.
- Bibliographer may query public external metadata to discover/update bibliography; Verifier may independently query public metadata to validate it. No other role makes external calls.
- No circumvention of paywalls, authentication, robots rules, rate limits, CAPTCHA, or platform terms.
- Every draft claim requires a verified direct quotation or an accurately located indirect quotation/paraphrase.
- A human approval is mandatory before source ingestion. Shutong drafts only after the scholar has asked questions, Noter has produced the relevant verified notes, and the scholar explicitly requests a draft.
- Enforce the evidence lineage: approved bibliography entry → properly ingested source → verified note → draftable claim → draft. Notes without an ingested paper source and drafts without verified notes are invalid states.
- When a lineage link is missing, Shutong presents the gap and asks the scholar to complete/approve the next action; it offers drafting only once every required link passes.

## Existing seams to extend

| Existing capability | Evidence | Plan use |
|---|---|---|
| npm/Bun launcher with a `shutong` binary | `shutong/package.json` | Publish this package and add first-run backend setup. |
| Python backend already declares citeindex and MCP dependencies | `packages/shutong-backend/pyproject.toml` | Extend the local backend rather than introduce a second service. |
| Paper manifest isolates sources and creates drafts/notes folders | `packages/shutong-backend/shutong_backend/papers.py:48-104` | Add bibliography, claims, audits, and readiness artifacts under the same paper. |
| Renderer generates host-specific MCP and skills | `shutong/src/cli/renderer.ts:1-95` | Generate the four specialist agents and scholarly skills for all three supported hosts. |
| Existing pipeline has checkpoint persistence | `packages/shutong-backend/shutong_backend/agents/pipeline.py:31-169` | Reuse its pause/resume pattern for bibliography and readiness gates. |

## Delivery phases

### Phase 1.5 — Project/work routing

**Goal:** let one scholar maintain several active research efforts without evidence leaking between them.

1. Add local project manifests for books, articles, and general research projects.
2. Add work manifests for papers and book chapters; book chapters reference their project's shared source library.
3. Add a workspace-planner to inspect local IDs, titles, and questions, then recommend continue/switch/create without changing the active workspace.
4. Require scholar confirmation before activation and pass the confirmed work ID to every specialist.
5. Preserve work-local notes, claims, audits, and drafts even when source membership is shared.

**Acceptance:** a source added through one book chapter is available to sibling chapters, while a note or claim created in one chapter is absent from every sibling chapter until explicitly recreated and verified there.

### Phase 0 — Package and first-run backend setup

**Goal:** `npm install -g shutong` has a trustworthy setup path on Codex, OpenCode, and Claude Code.

1. Convert `shutong/package.json` from workspace-only launcher metadata into publishable npm metadata, package files, versioning, and a release verification script.
2. Add `shutong setup` to discover Python 3.12+, create a user-local Shutong virtual environment, and install the packaged Python backend plus citeindex on first run.
3. Add `shutong doctor` checks for Python, backend import, citeindex, writable local data directory, and selected host configuration.
4. Make setup fail closed: when offline or unsupported, print the exact manual prerequisite command and do not write MCP configuration until the backend check passes.
5. Retain project-local configuration in `.shutong/config.toml`; never put corpus or credentials in the global npm directory.

**Likely files:** `shutong/package.json`, `shutong/src/index.ts`, `shutong/src/cli/doctor.ts`, new `shutong/src/cli/setup.ts`, `shutong/src/engine/config.ts`, release workflow/docs.

**Acceptance:** clean-machine setup succeeds for each host; offline setup ends with an actionable diagnostic and no broken MCP registration.

### Phase 1 — Paper artifact model and policy layer

**Goal:** a paper becomes the durable local boundary for bibliography, evidence, approvals, and audits.

1. Extend the paper manifest with explicit single-scholar policy, selected citation style, approved bibliography state, ingestion mode, and readiness state.
2. Add local, versioned artifact directories: `bibliography/`, `notes/`, `claims/`, `audits/`, and preserved `imports/`; keep existing `drafts/`.
3. Define schemas for bibliography entries, search-ledger rows, claim records, audit reports, approval decisions, copyright/access records, and readiness reports.
4. Preserve imported `.bib` and CSL-JSON bytes unchanged in `imports/`; generate normalized local metadata beside them. Do not claim a canonical format until the remaining metadata decision is made.
5. Add append-only scholar decision records for bibliography approval, ingestion authorization, and verifier override.

**Likely files:** `packages/shutong-backend/shutong_backend/papers.py`, new `.../paper_artifacts.py`, new schema files, `tests/test_papers.py`.

**Acceptance:** a new paper can persist and reload all artifacts without accessing another paper; invalid transitions (ingest before approval, draft before ready) return structured errors.

### Phase 2 — Source registry and compliant metadata adapters

**Goal:** broad but honest bibliography discovery from working adapters, not a list of aspirational platforms.

1. Port Jobfinder's configuration-driven registry pattern: source specification, adapter registration, health check, per-source timeout, normalization, deduplication, and isolated failures. Do not copy employment-specific data models.
2. Define `free`, `paid_api`, and `adapter_browser` source capabilities with scholarly fields: disciplines, periods, languages, regions, source types, rights/access policy, required credential, rate policy, output identifiers, and provenance.
3. Implement first adapters: Crossref, OpenAlex, Semantic Scholar, DOAJ, Open Library, pluggable catalogue adapter, OAI-PMH institutional repositories, and publisher metadata pages.
4. Record source, query, date, URL, response status, access state, and adapter version in the private search ledger.
5. Add rate limiting, response validation, deduplication by DOI/other identifier/title fallback, and an explicit `unavailable` result. Browser support remains a later capability; Google Scholar is not part of this first implementation set.

**Likely files:** new `packages/shutong-backend/shutong_backend/sources/` package, `.../tools/bibliography.py`, source-registry config, `mcp_server.py`, `rpc_server.py`, tests with frozen API fixtures.

**Acceptance:** any adapter failure is shown in the search ledger while successful adapters still return normalized candidates; no source body or paper artifact appears in an external request.

### Phase 3 — Bibliographer workflow and human approval gate

**Goal:** turn a topic/question into an approved 30–50 entry bibliography.

1. Implement `explore-bibliography` to generate transparent search concepts and use the registry.
2. Implement `format-bibliography` to screen direct relevance, normalize metadata, propose primary/secondary classification, and render an annotated 30–50 source shortlist in the configured style.
3. Implement `update-bibliography` to add clearly labeled contextual, opposing, or critical works only on scholar request.
4. Implement `scholar-reach` for public work/affiliation/contact discovery and optional unsent outreach drafts; store local provenance and never infer addresses.
5. Add the mandatory approval state machine: `approve`, `narrow`, `expand`, `reject`, and `correct classification`. Full bibliography, source-proposal, and ingestion operations must reject calls without approval.
6. Render Bibliographer prompts and skills for Codex, OpenCode, and Claude Code from one template source.

**Likely files:** new `agents/bibliographer.py`, new skills/templates, `papers.py`, `mcp_server.py`, `rpc_server.py`, `shutong/src/cli/renderer.ts`, host-renderer tests.

**Acceptance:** a user sees an annotated 30–50 direct-relevance bibliography and must approve it before a source is offered for ingestion; contextual/opposing work never appears unlabeled in the initial shortlist.

### Phase 4 — Copyright-aware ingestion

**Goal:** ingest only scholar-authorized, lawfully available material.

1. Implement `copyright-access` to classify candidates as open, licensed, user-provided, metadata-only, restricted, or unavailable and report lawful next steps.
2. Implement `ingest-source` modes: per-source approval, selected-batch approval, and an explicit pre-approved automatic rule recorded in the paper manifest.
3. Reuse current citeindex ingestion and post-ingest searchability verification; attach the intake receipt, source role, copyright/access record, original import reference, corpus identifier, and Merkle root to the paper.
4. Keep Ingestor unable to decide relevance, rights, or classification itself.

**Likely files:** ingestion handlers, `papers.py`, new rights/access module, host skill templates, `tests/test_mcp_tools.py`, ingestion integration tests.

**Acceptance:** restricted/unavailable sources generate an access report, never an acquisition attempt; each ingested document has an approved bibliography record, role, receipt, and successful search check.

### Phase 5 — Noter, claims, and Verifier reports

**Goal:** private Markdown notes accumulate into traceable paper evidence.

1. Implement Noter operations: keyword-in-context, passage capture, direct/indirect quotation records, summaries, text-reuse links within approved bibliography/corpus, and outline tags.
2. Store notes as Markdown with stable IDs and machine-readable frontmatter/sidecar fields that link approved bibliography entry, ingested source, corpus node, locator, claim, and verification state.
3. Implement claim records that require one or more note-backed direct or indirect quotations; drafts may reference only verified claims.
4. Implement `verify-bibliography` external metadata checks and local checks for duplicates, identifiers, formatting, primary/secondary proposals, source integrity, quotations, note claims, and draft claim links.
5. Implement plagiarism-risk analysis as a separate Verifier report, scoped to the bibliography/notes/corpus material; never present it as a plagiarism verdict.
6. Implement scholar override: report `pass`/`fail`/`uncertain`, evidence inspected, defect, affected claims, residual risk, and required scholar reason. Preserve every override append-only.

**Likely files:** new `agents/noter.py`, new `agents/verifier.py` or extension of `agents/integrity.py`, paper artifact modules, claim/citation tools, host templates, tests.

**Acceptance:** a note cannot be created without an approved bibliography entry and ingested source; every note has a stable source locator; each accepted claim traces to a verified note; an override remains visible in the final audit report.

### Phase 6 — Ready-to-draft gate and DOCX output

**Goal:** drafting begins only with approved, ingested, note-backed evidence.

1. Add `paper audit` checks for approved bibliography, required core-source ingestion, and verified notes that cover the scholar's intended outline.
2. Add a Shutong routing/checkpoint step: paper/topic questions go to Noter when notes are needed; Noter records the resulting local note artifacts before drafting is available. If bibliography approval, ingestion authorization, verification, or notes are missing, Shutong tells the scholar exactly which action is needed next.
3. Make the existing outline/draft pipeline consume paper claims/verified notes rather than raw retrieved passages alone, and require an explicit `draft` request from the scholar.
4. Reject an attempted draft with a structured readiness report when any gate is incomplete.
5. Retain Markdown for Noter and intermediary artifacts; add a DOCX export stage for an approved final draft, with citations preserved.
6. Defer venue-profile rules until a scholar selects a venue and supplies the relevant policy source.

**Likely files:** `agents/pipeline.py`, writing agents, `papers.py`, new exporter module, tests for each readiness failure and DOCX smoke export.

**Acceptance:** the pipeline cannot draft until all three readiness conditions pass; a final approved draft exports to DOCX without losing citations.

### Phase 7 — Cross-host release and documentation

**Goal:** same scholarly behavior on Codex, OpenCode, and Claude Code.

1. Generate the same agent charters and skills for each host while using each host's native MCP configuration format.
2. Add an end-to-end fixture: create paper → explore bibliography → approve → ingest → note → verify → readiness → draft export.
3. Test setup/doctor/host rendering in isolated temporary directories for all three hosts.
4. Publish npm package metadata, changelog, privacy statement, source-access policy, and migration guide from existing project layout.

**Acceptance:** one fixture produces equivalent paper artifacts and gates on all three host adapters; `npm pack` includes every required launcher/template asset and excludes corpus data.

## Implementation order and stop conditions

Implement phases 0–3 before any advanced note, plagiarism, or DOCX work. Stop and obtain a design decision if the unresolved note threshold or BibTeX/CSL normalization policy changes the artifact schema. Do not ship a source adapter without a fixture-backed parser/normalizer test and documented access policy.

## Deferred work

- Google Scholar/browser scraping and any platform-specific dynamic browser adapter.
- Collaborative/coauthor workspaces.
- Cloud LLMs or sending paper artifacts to external services.
- Empirical-study, dataset, IRB, and experiment provenance workflows.
- Automated outreach or publication submission.
