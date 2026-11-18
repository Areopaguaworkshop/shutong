# Evidence analysis workflow

Shutong keeps the existing agents and adds four skills. The main agent coordinates work and writes requested reports or short cited paragraphs from verified evidence. This feature does not establish autonomous whole-paper quality. Implementation: `shutong/src/cli/renderer.ts`, `packages/shutong-backend/shutong_backend/analysis.py` and `papers.py`.

| Responsibility | Owner | Skill / artifact |
|---|---|---|
| Define question, scope, method and validity criteria | Main agent with scholar; Bibliographer supplies coverage constraints | `analysis-plan` |
| Find relevant sources, editions, translations, opposing findings and gaps | Bibliographer | Annotated bibliography for scholar approval |
| Import approved sources | Ingestor | Ingested, integrity-checkable corpus |
| Calculate patterns and interpret passages | Noter calls backend; records interpretation separately | `text-analysis`, saved analysis, source-located notes |
| Compare findings, retain disagreements and coverage limits | Noter; main agent composes requested synthesis | `evidence-synthesis` |
| Inspect quotations, interpretation and citation consistency | Verifier | `citation-check`, review evidence |

These are skill responsibilities within existing roles, not four additional subagents. The backend stores calculations and provenance; it does not supply an independent reviewer. Role instructions are shipped in the Python templates and Bun host renderer.

## Run an analysis

First create the paper workspace, obtain bibliography approval, and ingest its selected sources. Use actual paper/source IDs in place of the illustrative values below. Call the public `shutong_analysis` tool:

```json
{
  "action": "run",
  "paper_id": "study",
  "mode": "collocations",
  "language": "en",
  "question": "Which expressions occur near the selected term?",
  "source_ids": ["approved-source-id"],
  "query": "virtue",
  "window": 5,
  "limit": 100
}
```

The response contains `analysis`, its generated `analysis_id`, and `record_sha256`. Runs are saved under the paper workspace's `analyses/` directory. Reopen with `action: "get"`, `paper_id` and `analysis_id`; this rechecks source integrity and detects changed source snapshots. The API schema and validation live in `analysis.py:22`.

| Mode | Inputs beyond question, language and source IDs | Meaning |
|---|---|---|
| `concordance` | `query`, optional `context` | Normalized token matches with exact source spans and surrounding text |
| `collocations` | `query`, optional `window` | Neighbor counts per target occurrence and document frequency |
| `contextual_sentiment` | `query`, required `rubric` | Context retrieval for agent interpretation; no automatic sentiment score |
| `quotation` | `query` containing the quotation | Case-sensitive exact agreement with ingested text |
| `text_reuse` | At least two sources, optional `minimum_tokens` | Equal normalized sequences across sources; default sequence width is eight tokens |

All modes accept `limit` (1–200). Context radius is 20–1000 characters; collocation windows are 1–20 tokens; reuse widths are 4–30 tokens. Runs are limited to 50 sources, 5,000 nodes and two million characters; reuse additionally caps candidate windows at 200,000. Returned results state truncation. See `analysis.py:85` and `analysis.py:215`.

## Interpret, review, then write

For contextual sentiment, call `annotate` with the latest record hash, the actual `model_id`, and an `annotations` array. Each item names `context_index` (zero-based), `target`, `speaker`, `rationale`, `label` and `confidence`. Supported labels are `favorable`, `unfavorable`, `neutral`, `mixed` and `uncertain`; confidence is `known`, `probable` or `speculative`. An annotation call replaces the previous annotations and resets review. Report unannotated and truncated contexts as coverage limits. See `analysis.py:265`.

Verifier inspects the exact returned record, checks source passages and interpretation, then calls `review` with `paper_id`, `analysis_id`, the inspected `record_sha256`, `outcome` (`pass`, `fail` or `uncertain`), `reviewer` and concrete `evidence`. Reviewer identity is supplied metadata, not authenticated proof of independence. Use a fresh `get` response before each update and serialize updates to a run; simultaneous writers are not coordinated across processes.

Noter links a finding by supplying `analysis_id` when adding a source-located note through `shutong_note`. Verification requires a current passing analysis review. Claim creation and paper audit reject stale analysis-linked notes; revising the analysis or its review requires renewed note verification. The main agent may then write an explicitly requested synthesis from verified notes and claims. Gates are implemented in `papers.py` (`_check_note_analysis`, `verify_note`, `add_claim`, `audit`).

## Method limits and installation

English uses Unicode word units; Chinese uses individual Han characters, not linguistic word segmentation. Normalized matching applies NFC and casefolding and ignores punctuation between tokens. Matches never cross corpus node boundaries. Reuse is evidence of shared sequences, not proof of borrowing or plagiarism; collocation counts do not establish statistical significance. Exact quotation agreement checks the ingested text, not the original page image. Merkle verification establishes local integrity, not semantic support or historical authenticity. These limits are saved in every run (`analysis.py:244`).

The default implementation is English/Chinese, rubric-based interpretation and exact sequence reuse. Automatic sentiment models, approximate reuse and additional language-specific analyzers are deferred pending concrete requirements. Recording model identity does not guarantee identical future interpretations.

Rebuild/update the bundled backend and restart the host's MCP server to expose `shutong_analysis`. Run the normal project initialization to add missing skills. Existing generated files are preserved unless forced; review template changes before replacing customized agent instructions. The implementation updates shipped templates, not personal host configurations. Host-generation coverage is in `shutong/test/cli.test.ts`.

See the [implementation plan](plans/2026-09-10-evidence-analysis-plan.md), [changelog](evidence-analysis-changelog.md), [package inventory](artifacts/evidence-analysis-package-audit.json), and [interactive workflow](artifacts/shutong-workflow.html).
