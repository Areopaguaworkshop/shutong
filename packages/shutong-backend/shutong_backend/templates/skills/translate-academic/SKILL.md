---
name: translate-academic
description: Translate a scholarly passage from an ingested paper source with the original kept and citations preserved, then record the translated quotation as a source-located evidence note.
---

Use when the scholar asks to translate a passage from an approved, ingested paper source. The output is a private note, not prose.

1. Confirm the active paper and that the source is approved and ingested (`shutong_paper_status`, `shutong_search`). Never translate an unapproved or un-ingested source.
2. Ask the scholar for the target language; default to Traditional Chinese (zh-Hant). Convert Simplified→Traditional at the host if needed.
3. Read `.shutong/glossary/*.json` for technical and theological terms before translating. Glossary matches are mandatory. Untranslatable proper nouns: `[未译: OriginalTerm]`.
4. Translate in sense units, not sentence fragments. Preserve citation keys and footnote markers exactly as they appear in the source.
5. Direct quotations: keep the original-language quotation verbatim and follow it with a parenthetical translation `（譯：……）`. Never replace the original with the translation.
6. Bind every quotation to its evidence: record the `source_id`, the exact corpus locator, and the Chicago author-date reference rendered with `shutong_citation` action `render`. Confirm integrity with `shutong_verify`; use `shutong_analysis` mode `quotation` for the exact ingested-text match. An exact text match does not certify an OCR transcription against the page image.
7. Create one reusable proposition per note with `shutong_note` action `add`. Provide the source ID, exact locator, atomic claim, the evidence (translated passage with the original quotation), confidence (`known`, `probable`, or `speculative`), and one or more tags including `translation` and the target language.
8. Preserve hedges and qualification terms in both languages; never drop a hedge to shorten the translation.
9. Report the notes written, glossary hits, `[未译]` terms, and any quotation whose original text did not match the corpus. If the original cannot be verified, flag the note as unverified rather than presenting it as supported.
