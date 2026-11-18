# Evidence analysis implementation plan

Status: implemented and validated on 2026-09-10. Authorized by the scholar on 2026-09-10.
Progress log: [implementation changelog](../evidence-analysis-changelog.md).

## Outcome and ownership

Keep the existing agent roles. Main agent coordinates and writes requested reports or short cited syntheses. Bibliographer proposes relevant source sets, editions, opposing scholarship and coverage limitations. Ingestor handles approved intake. Noter executes analysis through backend tools and creates evidence-linked findings. Verifier independently inspects results, quotations and claim support. No new text-analyzer agent.

Current contracts: `shutong/src/cli/renderer.ts:5`, `packages/shutong-backend/shutong_backend/templates/agents/bibliographer.md:11`, `packages/shutong-backend/shutong_backend/templates/agents/noter.md:11`. Current note-overlap helper: `packages/shutong-backend/shutong_backend/papers.py:339`. These are the implementation starting points, not claims of completed new capabilities.

## Clarifications

Questions sent: initial languages; rubric-based contextual sentiment versus automatic model scoring; exact versus approximate text reuse. No preference answers were received; the scholar instructed continuation. Implemented the stated defaults: English and Chinese, rubric-based interpretation, exact phrase reuse first. Chinese matching uses character units, not linguistic word segmentation. Future preferences can change this bounded scope.

## Deliverables

1. Backend analysis operations over explicitly scoped, approved and ingested source passages: concordance/collocation counts, contextual stance evidence, exact quotation checks and source-to-source text reuse. Reuse existing corpus loading and integrity checks; exclude failed evidence. Preserve the existing note-overlap tool as a distinct operation.
2. Paper-local saved analysis records: source IDs and hashes, exact locators/spans, method and parameters, results, coverage limits and review status. Calculated results and agent interpretation stay distinguishable. Invalid input, stale evidence and unsupported methods must fail clearly.
3. Focused skills: analysis-plan, text-analysis, evidence-synthesis and citation-check. Reproducibility metadata belongs in backend records, not a new agent. Analysis-plan identifies question, corpus scope, method, language handling and validity checks. Evidence-synthesis retains conflicting findings and gaps. Citation-check distinguishes exact quotation agreement from semantic support and bibliography formatting.
4. Host rendering and packaged Python templates expose the same role responsibilities and skills. Existing user data and host settings must remain untouched. Generated artifacts in temporary test projects prove integration.
5. Documentation and a changelog with actual completed work, decisions, test evidence and remaining limitations.

## Implementation sequence

- [x] Trace current corpus, paper, MCP/RPC and host-rendering paths.
- [x] Define bounded analysis inputs/results using the documented defaults.
- [x] Implement backend analysis and persistent provenance.
- [x] Expose operations through the supported tool surface.
- [x] Add skills and role routing to shipped host templates.
- [x] Test paper scope, integrity failures, exact locations/counts, records and rendered hosts.
- [x] Verify Bun packaging still excludes personal data and includes new runtime resources.
- [x] Complete changelog and usage documentation with honest limitations.

## Acceptance checks

Use synthetic corpus data, not personal research. Tests must distinguish allowed versus unrelated sources; reject tampered/failed evidence; assert known counts, quotation spans and cross-source overlaps; preserve ambiguous sentiment as interpretation requiring review; save reproducibility metadata; and exercise the public tool dispatch plus generated host files. Run focused Python tests, Bun typecheck/tests, and an actual package inventory check. No registry publication or external analysis of personal content.

## Reference adaptations

Adapt concepts with Shutong-specific instructions rather than copying the reference project's agent architecture:

- [ARS Research Architect](https://github.com/Imbad0202/academic-research-skills/blob/main/deep-research/agents/research_architect_agent.md): explicit method and validity criteria → analysis-plan skill.
- [ARS Synthesis Agent](https://github.com/Imbad0202/academic-research-skills/blob/main/deep-research/agents/synthesis_agent.md): evidence matrices, disagreements and coverage → evidence-synthesis skill.
- [ARS Citation Compliance](https://github.com/Imbad0202/academic-research-skills/blob/main/academic-paper/agents/citation_compliance_agent.md): citation/reference consistency → citation-check skill.
- [ARS Reproducibility Pattern](https://github.com/Imbad0202/academic-research-skills/blob/main/shared/artifact_reproducibility_pattern.md): input/configuration recording and model-output limitations → saved analysis records.

These references were inspected in the preceding design discussion. No third-party skill code is imported.
