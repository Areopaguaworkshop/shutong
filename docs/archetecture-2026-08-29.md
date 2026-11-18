# Shutong architecture direction — 2026-08-29 (updated 2026-08-30)

## Status

**Implemented baseline; keep this document as the architecture contract.** The
2026-08-29 design is now reflected in the local paper/workspace workflow:
confirmed work scoping, approved-source retrieval, checkpointed research state,
fail-closed evidence gates, and local-only paper artifacts. Remaining items in

> **Revision 2026-11-17 — agent layer removed.** Shutong now ships one MCP server
> and one skill pack, with no host agent definitions and no per-role model config.
> The roles below are still the operating model, but each is a skill:
> Bibliographer → `explore-bibliography`, Ingestor → `ingest-source`, Noter →
> `noter`, Verifier → `verify-bibliography`, Workspace Planner →
> `workspace-planner`, conductor → `AGENTS.md`. Independence of the Verifier is
> now procedural, not structural: it runs in the author's context, and the
> backend gates are the only hard guarantee. See
> `docs/plans/2026-11-17-mcp-skills-only-plan.md`.
the implementation plan are explicitly marked as future or non-goal work.

## Product thesis

Shutong is an academic-research helper, analogous in interaction model to an agent harness such as oh-my-agent or oh-my-codex, but it is **not an autonomous researcher**. Its unit of work is one paper project. It helps a scholar find, ingest, read, structure, cite, draft, and audit material; the human researcher retains responsibility for research questions, interpretive judgements, source selection, and publication decisions.

The existing project already supports the appropriate foundation: a host-agnostic backend-as-agent model (README.md:16, 29-42), source ingestion into a hash-verified corpus (README.md:20-22), and active paper workspaces that restrict search to approved sources (README.md:115-126). A new paper currently has a question, source policy, drafts, and notes directories (packages/shutong-backend/shutong_backend/papers.py:48-57); it records primary, secondary, and unknown source roles (packages/shutong-backend/shutong_backend/papers.py:60-70).

## Target operating model

```text
Human scholar — owns questions, judgement, approval, authorship
        │
        ▼
Workspace Planner — proposes, never performs, a project/work switch
        │
        ▼
Shutong — confirmed-work conductor and evidence-policy enforcer
 ├─ Bibliographer — discover and normalize candidate scholarship
 ├─ Noter         — make reusable, cited reading notes and claim records
 ├─ Verifier      — independently audit all generated scholarly artifacts
 └─ Ingestor      — acquire and index permitted sources (may later merge into Bibliographer)
        │
        ▼
Paper workspace — manifest · approved corpus · bibliography · notes · draft · audit trail
```

## Projects, works, and switching

A scholar may maintain several projects, but every agent action has one confirmed active **work**. A standalone article is a project with one paper work. A book is a project with chapter works: its chapters share one project bibliography and ingested-source library, while each chapter keeps separate notes, claims, verifier reports, and drafts.

```text
New request → Workspace Planner → continue / propose switch / propose new work
                                      │
                         scholar confirms target project + work
                                      │
                                      ▼
                           Shutong → four specialist agents
```

The planner may inspect only local project/work metadata (IDs, titles, questions, and stage summaries). It must never infer consent from a topical match, silently activate a different work, or let an agent rely on a mutable global workspace without the confirmed work ID. For cross-work reuse, bibliography entries and source records may be referenced from a book's shared library; notes and claims must be explicitly transferred and re-verified in the destination work.

`Shutong` should dispatch a specialist only when its artifact is needed, collect the result into the paper workspace, and require verification before the result can become a citable paper claim. Bibliographer discovery is explicitly allowed to use the open web and scholarly-index platforms. It should never silently turn a discovery result, an unverified URL, or model memory into evidence.

## Agents and artifact contracts

| Agent | Owns | Required output | Must not do |
|---|---|---|---|
| **Shutong (main)** | Paper manifest, task routing, human checkpoints, artifact handoff, final evidence policy, and drafting from verified notes | Paper state, next scholar decision, and—only on an explicit request—a draft grounded in verified notes | Draft from discovery results or raw sources without notes; claim independent scholarly authority; or bypass the verifier |
| **Bibliographer** | The only outward-facing research role: question scoping; public-metadata queries to open-web and scholarly-index platforms; primary/secondary bibliography discovery and updates; related scholar/work and publicly available institutional-contact discovery; bibliographic normalization; source acquisition requests | A 30–50 entry, direct-relevance annotated bibliography in the paper's selected standard style, with proposed primary/secondary classification and verified/candidate state; private local search ledger: platform/query/date, source URL, access status, identifiers, rationale, public-contact provenance, and verification status | Send paper files, notes, contacts, or research state to an external service; present a lead as a read or verified source; treat its proposed primary/secondary classification as final; invent or infer contact information; collect non-public personal data; change the approved corpus without authorization |
| **Noter** | Corpus-bound reading support: keyword-in-context search, passage capture, quotation selection, text-reuse analysis, summaries, and claim-to-evidence links | Atomic notes, each with source locator, quoted/paraphrased text, tags, relation to question/outline, and verification status | Produce source-free assertions or promote a summary into evidence without a locator |
| **Verifier** | Independent checks of bibliography fields, ingest results, citation resolution, Merkle integrity, note claims, quotations, and draft claim-evidence links; public-metadata queries for independent source verification | Append-only audit report: pass/fail/uncertain, evidence inspected, defect, and corrective action | Send paper files, notes, contacts, or research state to an external service; perform broad discovery; rewrite the audited artifact; or convert uncertainty into a pass |
| **Ingestor** | Permitted source intake through citeindex and searchability confirmation | Ingest receipt: provenance, corpus ID, Merkle root, node count, format, and search check | Judge relevance or bibliographic correctness alone |

The current project already contains narrow `ingestor` and `verifier` agent templates: ingestion reports corpus path, Merkle root, node count, type, and searchability (packages/shutong-backend/shutong_backend/templates/agents/ingestor.md:13-17); verification can audit all or one document and resolve citations (packages/shutong-backend/shutong_backend/templates/agents/verifier.md:11-15). The present `researcher` is corpus-only and verifies results before producing Chicago author-date citations (packages/shutong-backend/shutong_backend/templates/agents/researcher.md:14-20). The proposed Bibliographer and Noter sharpen that responsibility split rather than adding a general-purpose research agent.

## Evidence lifecycle

**Hard evidence lineage:** `approved bibliography entry → properly ingested source → verified note → draftable claim → paper draft`. A missing link blocks the next stage. Bibliographer creates and updates bibliography; Ingestor preserves approved sources; Noter owns the evidence-to-note link and can only create a paper note from an ingested source; Shutong drafts only from verified notes. Shutong must tell the scholar which link is missing, ask them to complete or approve the next step, and offer a draft only after the full lineage is complete.

1. **Scope.** The scholar and Shutong establish a paper question, boundaries, method, and source policy.
2. **Explore.** Bibliographer turns the paper question into search concepts, searches the available source market, and records provenance in a private search ledger. It finds primary and secondary candidates, related works, and publicly available institutional academic contacts. A lead is not evidence.
3. **Bibliography checkpoint (mandatory).** Bibliographer de-duplicates and verifies bibliographic metadata, judges direct relevance against the paper question, proposes primary/secondary classification, and returns a 30–50 entry annotated shortlist in the paper's selected standard style. The scholar must explicitly approve, narrow, expand, reject, or correct classifications. Only after approval may Bibliographer produce the full bibliography and propose sources for ingestion.
4. **Approve and ingest.** The scholar authorizes sources; Ingestor adds them via citeindex and records the intake receipt.
5. **Read and note.** Noter works only from properly ingested, paper-approved corpus material. Every reusable note stores its approved bibliography entry, exact corpus locator, and verification status. If no approved and ingested source exists for a question, Noter reports the gap rather than creating a note.
6. **Verify.** Verifier audits bibliography, source identity, corpus integrity, citations, quotations, and note/draft claim alignment.
7. **Ask and note.** The scholar asks questions about the paper/topic. Shutong decides when to route each question to Noter; Noter creates or updates the needed verified notes. This phase can repeat until the scholar judges the note base useful.
8. **Explicit draft request.** Only after notes are available may the scholar ask Shutong to draft. Shutong arranges verified notes against the approved outline and writes from them. Claims without supporting verified notes remain visible as gaps, not completed prose.
9. **Release.** The scholar reviews the audit trail and makes the final authorship/submission decision.

After the direct-relevance bibliography is approved, the scholar may invoke a bibliography update to add **contextual**, **opposing**, or **critical** work. Those additions are a distinct layer and are never silently mixed into the direct-relevance shortlist.

### Search and scholar-contact policy

- **Source discovery is open by default.** Bibliographer may search the open web and scholarly-index platforms to find sources available in the market. Every result retains its platform, query, retrieval date, URL, and access status in the search ledger.
- **Outbound boundary.** Bibliographer may query external platforms for public metadata and reach outward again whenever the scholar requests a bibliography update. Verifier may independently query public metadata to check source identity and bibliographic fields. Each sends only the minimal query/identifier and receives public metadata; paper content, notes, locally stored contact records, source files, and research state never leave the workspace. All other roles remain inside their paper-scoped local corpus and artifacts.
- **Coverage is broad by default.** The registry should support the largest practical set of sources, categorized by access route rather than pretending all platforms have equal coverage: `free`, `paid_api`, and `adapter_browser`.
- **Related-work mapping is part of discovery.** Bibliographer traces a relevant scholar's public publication record and co-cited/related works, but records the evidence for each relation.
- **Contact discovery is limited to public professional data.** It may record an email only when the scholar or their institution has published it for professional contact, with the page URL and retrieval date. It must not guess email patterns, enrich private data, or imply that public availability is consent to contact.
- **Outreach is scholar-controlled.** Shutong may prepare a factual, source-grounded outreach draft and a contact rationale for the scholar's review. It must never send messages, create accounts, or represent the scholar.
- **Search is not evidence.** A search result becomes usable evidence only after the scholar approves the source, Ingestor preserves it through citeindex, and Verifier confirms its identity, integrity, and locator.
- **Compliant access only.** Prefer official APIs and openly available feeds; use a browser adapter only for permitted rendering of public pages. Never bypass CAPTCHA, authentication, rate limits, robots rules, paywalls, terms of service, or other access controls. When access is blocked, record the limit and offer the lawful route (API key, library access, user-provided export, or manual download).

### Search-source registry and planned skills

The Bibliographer needs a **source registry**, not one universal scraper. This is internal infrastructure, never its output. Each source declares its scholarly scope, disciplines/languages/regions, access category, credential needs, rate policy, permitted fetch method, adapter availability, output fields, and health state. This makes broad coverage additive: an unavailable or failed source is recorded without aborting discovery on all other sources.

| Access category | Examples of source families | Preferred route | Result status |
|---|---|---|---|
| `free` | OpenAlex, Crossref, DOAJ, CORE, PubMed/Europe PMC, repositories, library catalogues, publisher metadata, open journals | Official API, OAI-PMH/RSS, public metadata or HTML | `discovered` / `metadata_verified` |
| `paid_api` | Licensed bibliographic indexes and publisher/library services | User- or institution-supplied credential through an explicit adapter | `metadata_verified` / `access_requires_license` |
| `adapter_browser` | Dynamic public pages and platforms without a suitable public API | HTTP parser first; then browser rendering for allowed public pages | `discovered` / `blocked` / `login_required` |

Initial skill specifications (design only; do not implement until this architecture is approved):

| Skill | Used by | Contract |
|---|---|---|
| `explore-bibliography` | Bibliographer | Expand the paper topic and question into a transparent multi-platform search plan; query the registry; emit deduplicated candidate works and the private search ledger, including failures and coverage gaps. |
| `format-bibliography` | Bibliographer | Select 30–50 direct-relevance verified/candidate works for the user's actual question, propose primary/secondary classifications, normalize their metadata, and render an annotated bibliography in the paper's selected standard (Chicago author-date initially; other styles by paper policy). |
| `update-bibliography` | Bibliographer | On scholar request, extend an approved bibliography with contextual, opposing, or critical work; label the reason for each addition and return to the same approval checkpoint. |
| `scholar-reach` | Bibliographer | Map related public works, affiliations, and institution-published professional contacts; produce a reviewable contact rationale and optional unsent outreach draft. |
| `source-adapter` | Bibliographer / Ingestor | Apply one registry entry through its approved API, feed, parser, or browser route; enforce source-specific pacing and return normalized provenance plus access status. |
| `verify-bibliography` | Verifier | Independently check identifiers, titles/authors/venues, duplicate merges, primary/secondary classification, style rendering, access claims, and public-contact provenance. |
| `ingest-source` | Ingestor | Present the scholar with individual, batch, or pre-approved automatic ingestion choices; preserve selected material with citeindex and record an intake receipt. |
| `copyright-access` | Bibliographer / Ingestor | Classify source availability and rights as open, licensed, user-provided, metadata-only, restricted, or unavailable; provide lawful access options and never acquire or bypass restricted material. |

The current `cite-research` skill verifies quoted corpus passages and renders Chicago author-date citations (packages/shutong-backend/shutong_backend/templates/skills/cite-research/SKILL.md:8-11). `format-bibliography` complements it: it is the Bibliographer's standard-reference-list skill, operating before sources become corpus evidence. Scrapling and a real-browser adapter may be implementation options for `source-adapter`; they are transport choices, not evidence or authorization mechanisms.

**Human-in-the-loop rule:** Bibliographer stops at the annotated-shortlist checkpoint. The scholar's recorded choice—`approve`, `narrow`, `expand`, or `reject`—is required before a full bibliography, source-approval request, or ingestion dispatch. This is a scholarly decision, not a convenience prompt.

**Classification rule:** ARS's Bibliographer has a documented search strategy, inclusion/exclusion criteria, two-pass relevance screening, deduplication, and annotated-bibliography output, but no explicit primary/secondary source-classification workflow in the reviewed instructions ([ARS Bibliographer](https://raw.githubusercontent.com/Imbad0202/academic-research-skills/main/deep-research/agents/bibliography_agent.md), lines 45-116). Shutong therefore keeps this as a transparent proposed classification subject to scholar correction at the bibliography checkpoint.

### Jobfinder pattern to reuse

Jobfinder's `SourceRegistry` loads configuration, registers only available adapter implementations, dispatches each source independently, and reports per-source failures rather than failing the whole search (jobfinder/core/sources/base.py:82-245). Its base adapter separates search, optional detail enrichment, and health checks (jobfinder/core/sources/base.py:40-79). That is the appropriate model for Shutong's diverse scholarly platforms.

The registry must be scholarly rather than employment-oriented: route selection needs subject domain, source type (primary/secondary), language, geographic tradition, publication period, access route, and reliability/provenance. Browser rendering is an optional final transport route for allowed public material; it is not a license to defeat a platform's controls.

The existing pipeline already has research, outline, draft, style, quality, and review stages (packages/shutong-backend/shutong_backend/agents/pipeline.py:31-41), pauses at checkpoints (packages/shutong-backend/shutong_backend/agents/pipeline.py:128-154), and uses corpus retrieval as its research stage (packages/shutong-backend/shutong_backend/agents/pipeline.py:187-206). The design change is to make the reusable bibliography and note artifacts explicit before drafting, with verifier gates at the transitions.

## Reuse from reference systems

### oh-my-agent / oh-my-codex

Adopt the **shape**, not a software-engineering clone:

- One top-level operating contract plus portable, narrow agent and skill definitions. oh-my-agent describes a portable `.agents/` source of truth projected into host-native layouts and artifact-based verification ([oh-my-agent README](https://raw.githubusercontent.com/first-fluke/oh-my-agent/main/README.md), lines 4-18, 68-70).
- Role ownership, bounded delegation, resumable sessions, and independent verification. oh-my-codex similarly emphasizes role-based orchestration, planning, lifecycle hooks, and verification ([oh-my-codex README](https://raw.githubusercontent.com/realsigridjin/oh-my-codex/main/README.md), lines 26-57).
- Replace engineering gates (typecheck/test/lint) with scholarly gates: source identity, authorization/provenance, extraction completeness, locator resolution, Merkle integrity, claim-evidence alignment, and bibliography-format validation.

Do not transplant their large generic agent catalog or autonomous execution modes. A four-role scholarly team plus the conductor is the smallest design consistent with this product thesis.

### Academic Research Skills (ARS)

ARS currently exposes four top-level reusable skill packs—deep research, paper writing, paper review, and a pipeline orchestrator—and its architecture documents a ten-stage, checkpointed workflow with mandatory integrity gates ([ARS README](https://raw.githubusercontent.com/Imbad0202/academic-research-skills/main/README.md), lines 220-235; [ARS architecture](https://raw.githubusercontent.com/Imbad0202/academic-research-skills/main/docs/ARCHITECTURE.md), lines 34-80). It supplies many specialist roles inside those packs; those are a catalogue of behaviors, not a reason to recreate dozens of Shutong agents.

Adopt or adapt these behaviors into the four roles above:

| ARS behavior | Shutong home | Keep / change |
|---|---|---|
| Research-question brief, methodology blueprint, annotated bibliography | Bibliographer + Shutong | Keep as paper-start artifact; add primary/secondary and corpus-access fields |
| Corpus-first, search-fills-gap flow and explicit skipped-source reasons | Bibliographer | Keep; make scholar approval mandatory before ingestion |
| Claim verification with high-impact prioritization | Verifier | Keep; make every accepted claim resolve to Shutong corpus locators and Merkle checks |
| Citation anchors and formatter refusal for unlocatable citations | Noter + Verifier | Keep; make locator mandatory at note creation, not only at finalization |
| Argument map, outline, draft, revision response | Shutong using verified notes | Keep only after the evidence lifecycle above |
| Devil's advocate / peer review / revision loop | Future verifier mode | Defer until core evidence artifacts and audits are reliable |
| Collaboration-depth scoring and cross-model review | Optional future advisory | Defer; it does not establish paper correctness |

ARS explicitly distinguishes integrity checking from proving that research procedures happened or data are authentic ([ARS README](https://raw.githubusercontent.com/Imbad0202/academic-research-skills/main/README.md), lines 88-92). Shutong should make the same boundary clear, while its corpus hashes give it a stronger check on the material actually ingested.

## Initial paper data model (conceptual)

Keep the existing paper manifest and folders. Add no new storage format until the following artifacts are agreed:

- `bibliography`: candidate and approved entries, each with type, identifiers, access/provenance, scholar confirmation, and verification state.
- `search-ledger`: query and platform provenance for discovery, plus public-contact provenance and the scholar's outreach decision; it is not a source of paper claims.
- `source-registry`: versioned source capability records (scope, access category, policy, credential requirement, adapter, rate limit, health) kept separate from paper data so every paper can use the same searchable market map.
- `notes`: atomic notes keyed to bibliography entry and corpus node/locator; tags and optional outline links make them reusable and rearrangeable.
- `claims`: a draft assertion linked to one or more note IDs, a strength label, and verifier status.
- `audits`: append-only reports for ingestion, bibliography, notes, citations, and claims.

## Decisions recorded — 2026-08-29

| Area | Decision |
|---|---|
| Workspace | One scholar, one paper workspace for the first release. No coauthor workspace or shared approvals. |
| Distribution | Shutong is published as an npm package. The npm CLI installs/scaffolds the host integration, skills, paper-workspace layout, and local backend configuration; the research corpus and all paper artifacts stay in the user's chosen local project directory. |
| Backend installation | The npm CLI performs a first-run local setup of the Python/citeindex backend. If setup cannot run (offline, unsupported Python, or user choice), it reports the exact prerequisite command and does not create a broken host configuration. |
| Host support | The first npm release supports Codex, OpenCode, and Claude Code together. |
| Bibliography | The first result is 30–50 directly relevant annotated works. A scholar approval gate is mandatory. `update-bibliography` later adds contextual, opposing, or critical work on request. |
| Ingestion | `ingest-source` presents three scholar-controlled modes: approve individually, approve a selected batch, or approve a pre-defined automatic rule. Every mode remains subject to the copyright/access policy. |
| Copyright and availability | `copyright-access` reports rights/access status and lawful options; it does not bypass restrictions or obtain unavailable materials. |
| Academic contacts | Bibliographer may record only publicly published professional academic contacts and may draft, but never send, outreach. |
| Notes | Notes are private working material in the individual paper workspace. |
| Claims | Every claim must have a verifiable citation/quotation link—direct quotation or accurately located indirect quotation/paraphrase. |
| Text reuse and plagiarism | Text reuse belongs in the bibliography/note evidence scope. Plagiarism-risk analysis is a distinct Verifier responsibility. |
| Verification override | A scholar may override `fail` or `uncertain`, but Shutong presents the full report and permanently records the decision, reason, affected claims, and residual risk. |
| Privacy | Bibliographer may query external platforms for public metadata and Verifier may independently verify that metadata externally. Paper files, notes, source files, locally stored contact records, and research state remain local; no cloud model or external service receives them. Other agents do not make external calls. |
| Initial metadata adapters | Implement metadata-first adapters for Crossref, OpenAlex, Semantic Scholar, DOAJ, Open Library plus a pluggable catalogue adapter, institutional repositories/OAI-PMH, and publisher metadata pages. Keep Google Scholar as a later cautious browser adapter. |
| Stage outputs | Noter writes Markdown; ingestion preserves each original BibTeX and CSL-JSON import unchanged. Final drafts export DOCX. Keep Markdown as the internal interchange where practical. |
| Scope | Literature-based humanities work is first, with future expansion to other domains only after the evidence workflow is mature. |
| Ready-to-draft gate | All three are required: approved bibliography, ingested core sources, and verified notes sufficient for the scholar's intended outline. Shutong routes questions to Noter to build this base; Shutong drafts only when the scholar explicitly asks. |
| Initial note threshold | Enforce at least one verified note mechanically, then require the scholar to judge whether the note set covers the intended outline. A per-section threshold is deferred until real paper workflows show it is needed. |
| Evidence lineage | An approved bibliography entry must lead to a properly ingested source, which must lead to a verified note before it can support a draftable claim. No notes without ingestion; no drafts without notes. |
| Coordinator checkpoints | At every missing or incomplete lineage link, Shutong explains the gap and presents the next scholar action (approve bibliography, authorize ingestion, ask/approve notes, resolve a verification report). It offers drafting only after all required links pass. |

### Venue requirements, clarified

By “venue rules” I mean a target journal's or publisher's requirements: citation style, word limit, manuscript template, abstract length, bibliography format, and any policy requiring disclosure of AI assistance. This is not a first-release requirement. When the scholar selects a venue later, Shutong can add a read-only venue profile and check the final DOCX against it; it must never invent a rule when no source is provided.

The existing paper directory already provides `drafts/` and `notes/`, so this is an extension of the paper boundary—not a global knowledge base (packages/shutong-backend/shutong_backend/papers.py:53-57).

## Implementation status — 2026-08-29

The paper evidence workflow is implemented locally: a paper begins with a draft bibliography, explicit approval unlocks paper sources, sources are marked ingested only from the local citeindex source registry, lawful-access record, and scholar-selected ingestion authorization, notes require an ingested source plus locator, verified notes become verified claims, and the audit requires at least one verified claim (packages/shutong-backend/shutong_backend/papers.py). Original BibTeX/CSL-JSON imports and annotated shortlist artifacts are preserved per paper. Bibliographer metadata discovery currently covers Crossref, OpenAlex, Semantic Scholar, DOAJ, and Open Library with per-platform provenance and errors; it never acquires full text (packages/shutong-backend/shutong_backend/tools/bibliography.py). A project/work workspace layer now creates book, article, and research projects; book chapters share their project source library while preserving work-local evidence and drafts. The Workspace Planner only recommends a transition and requires explicit scholar confirmation before activation (packages/shutong-backend/shutong_backend/workspaces.py). A paper draft context exposes only verified claims after an explicit scholar request; a local DOCX export refuses to run before the same gate passes. The initializer ships Bibliographer, Noter, Ingestor, Verifier, and Workspace Planner skills for Codex, OpenCode, and Claude Code. An end-to-end test covers bibliography approval → authorized ingestion → verified note → verified claim → explicit draft → DOCX export.

## Non-goals for the first architecture increment

- Autonomous publication, correspondence, submission, or research decision-making.
- Claiming that a citation audit proves the truth of a source or the validity of an external experiment.
- A general multi-project memory that leaks material across papers.
- A large swarm of writing/review agents before bibliography, notes, locators, and audit trails work end to end.
