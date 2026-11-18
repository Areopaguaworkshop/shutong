# Shutong 書童 — Project Instructions

<!-- SHUTONG:BEGIN — do not remove this marker -->

## Scholar Principle

Never state a fact without a citation.

- Every factual claim must trace to a corpus source or a file + line number.
- If no citation is available, say exactly: "No citation available for this claim in the current corpus."
- Distinguish clearly: known (corpus-cited) / probable (evidence noted but indirect) / speculative (clearly labelled as such).
- Citation format: Chicago author-date — (Author Year, page).

## Shutong Roles

Shutong ships no agent definitions. The primary host agent plays the conductor:
it confirms the active work, loads the skill that owns the requested artifact,
enforces the evidence lineage, and drafts only from verified notes after an
explicit scholar request.

Route by skill, not by subagent:

| Request | Skill |
|---|---|
| Discover or update a bibliography | `explore-bibliography` |
| Check lawful access before intake | `copyright-access` |
| Ingest an approved source | `ingest-source` |
| Read, quote, translate, or note a passage | `noter` with `text-analysis`, `evidence-synthesis` |
| Audit bibliography, integrity, notes, claims | `verify-bibliography` with `verify-corpus`, `citation-check` |
| Start, resume, or switch a project/work | `workspace-planner` with `paper-workspace` |

If the host can spawn subagents, delegation is the host's choice. The skill text
carries the role, so a subagent must still load that skill. Shutong itself ships
no `permission.task` topology and no per-role model.

The legacy `researcher` role is not part of this paper-scoped workflow.

## Session Start

At the start of a session, call `shutong_state_wake_up` to load cross-session
research context (passport, recent sessions, knowledge graph). If it returns
context, incorporate it before answering. Record significant sessions with
`shutong_state_record_session`.

## Research Protocol

Before answering any research question:
1. Call `shutong_search` with the query to check the local corpus.
2. Call `shutong_verify` on the top results before quoting them.
3. If `shutong_verify` returns FAIL for a node, mark it [UNVERIFIED] and exclude it from your answer.
4. Do not answer factual scholarly questions from parametric memory alone.
5. If the corpus is empty, say: "No documents ingested yet. Use the `ingest-source` skill to add a source."

## Translation Protocol

Translation is a host-agent task, not a Shutong backend workflow; the output is a
private note, not prose. Use the translate-academic skill.

1. Confirm the source is approved and ingested. Ask the scholar for the target
   language; default to Traditional Chinese (zh-Hant).
2. Read `.shutong/glossary/*.json` in that language first; glossary matches are mandatory.
   Untranslatable proper nouns: `[未译: OriginalTerm]`.
3. Preserve citation keys and footnote markers exactly as they appear.
4. Direct quotations: keep the original-language quotation verbatim and follow it
   with a parenthetical translation `（譯：……）`. Never replace the original.
5. Bind every quotation to its `source_id`, exact corpus locator, and a Chicago
   author-date reference rendered with `shutong_citation`. A translated quotation
   is evidence only when the verbatim original and locator are recorded.
6. Record the note with `shutong_note` action `add`, with confidence (`known`,
   `probable`, or `speculative`) and tags including `translation` and the target
   language.

## Coding Discipline

1. Think before coding. State assumptions. Ask if unclear.
2. Simplicity first. Minimum code. No speculative features.
3. Surgical edits. Touch only what the task requires.
4. Goal-driven. Define success criteria. Verify each step.

## Corpus

- Corpus root: `./corpus/`
- Library: `./library/`
- Glossaries: `./.shutong/glossary/`

## Corpus Snapshot

<!-- SHUTONG:CORPUS:BEGIN -->
- Not included in the public repository. Run `shutong-backend sync` after adding
  your own sources; the snapshot lists only document titles from your local corpus.
<!-- SHUTONG:CORPUS:END -->

<!-- SHUTONG:END -->
