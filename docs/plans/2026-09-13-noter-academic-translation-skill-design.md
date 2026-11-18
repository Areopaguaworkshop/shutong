# Design: Citation-aware translation skill for Noter

Date: 2026-09-13
Status: Approved

## Problem

Noter has no translation capability, and no existing skill handles **academic
translation with citation information**. The backend pipeline
(`shutong_backend/translation/pipeline.py`) preserves citation keys only as
opaque strings, never handles direct quotations, and never links translated
output back to citations or the evidence gate.

The correct behavior already exists as an ad-hoc script, not a skill:
`papers/<paper-id>/translations/<source>/tools/translate_units.py:31-41`
keeps Latin/Greek/French quotations in the original with a parenthetical
`（譯：…）` translation, and preserves OCR damage rather than reconstructing.

The upstream repo `Imbad0202/academic-research-skills` (ARS) has **no
translation skill** (verified at commit `91fc74d`); its only cross-language
agent (`abstract_bilingual_agent.md`) is contractually anti-translation. Only
citation-integrity invariants are reusable as concepts. ARS is CC-BY-NC 4.0;
no code is copied.

## Decision

Deliver academic translation as a **prompt-only skill/mode** for Noter. No
Python changes, no note-schema changes. A translated passage becomes an
ordinary `evidence-v1` note, so it flows through the existing
verified-note → claim → draft gate unchanged.

Scope answers from the scholar:
- Citation-aware translation notes (not a separate translator lane).
- Target language chosen by the scholar, default **zh-Hant (Traditional)**.
- Direct quotations: **original kept verbatim + parenthetical `（譯：…）`**
  translation; the original is never replaced.

## Skill: `translate-academic`

1. Confirm the active paper and that the source is approved and ingested.
2. Ask the scholar for the target language; default zh-Hant.
3. `shutong_glossary_lookup` first; glossary matches are mandatory; unmatched
   proper nouns → `[未译: Term]`.
4. Translate in sense units; preserve citation keys and footnote markers.
5. Direct quotation rule: verbatim source-language quote followed by `（譯：…）`.
6. Bind each quotation to `source_id` + exact corpus locator + Chicago
   author-date (`shutong_citation` action `render`); check with `shutong_verify`
   and `shutong_analysis` mode `quotation` for the exact-match check.
7. Emit via `shutong_note` action `add`; confidence
   `known|probable|speculative`; tags include `translation` + language.
8. Report notes written, glossary hits, `[未译]` terms, and any quotation whose
   original match failed.

## Install surface (four real edit sites)

| File | Change |
|---|---|
| `packages/shutong-backend/shutong_backend/templates/skills/translate-academic/SKILL.md` | skill source of truth |
| `packages/shutong-backend/shutong_backend/templates.py` `_SKILL_FILES` | register for `.shutong/skills/` |
| `shutong/src/cli/renderer.ts` `skillTemplates` | host installs |
| `templates/agents/noter.md` + renderer agent prompts | Noter translation mode |
| `AGENTS.md`, `CLAUDE.md`, `templates/AGENTS.md.j2` | Translation Protocol |

Generated copies refresh with `shutong init --force` (hosts) and
`python -m shutong_backend.cli init` (`.shutong/`).

## Reused from ARS (concepts only)

- Verbatim quote + precise locator invariant; bare citation is refused.
- Direct-quote anchor ≤ 25 words.
- "Translations of foreign-language primary sources are independently
  verifiable."
- Protected-hedge preservation (from `abstract_bilingual_agent.md`).

## Skipped (YAGNI)

- Fixing `translation/pipeline.py` quotation handling — add when the prompt
  path demonstrably falls short.
- New translator agent, note-schema fields, OpenCC code.
- Reviving `shutong_translate` / glossary MCP tools: the
  2026-08-31 MCP reduction plan deliberately moved translation to the host.
- Dead `translate-zh` skill and orphaned `.shutong/agents/translator.md`
  (untracked, never regenerated) are deleted.

## Verification

Run the skill on one real passage from `silvas-2005-asketikon-intro` and assert:
note has `source_id` + `locator`, the verbatim original is present in the
corpus, the citation renders Chicago author-date, and the original was not
replaced. Confirm `git diff --stat` shows no Python or schema change.
