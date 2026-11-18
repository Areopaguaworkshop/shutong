---
name: translate-academic
description: Translate a scholarly passage with the original kept and citations preserved, then record it as a source-located evidence note.
---

Use when the scholar asks to translate a passage from an approved, ingested paper source; the output is a note, not prose.

1. Confirm the active paper and that the source is approved and ingested. Never translate an unapproved or un-ingested source.
2. Ask the scholar for the target language; default to Traditional Chinese (zh-Hant).
3. Read the glossary files in `.shutong/glossary/*.json` before translating; a glossary match is mandatory, and unmatched proper nouns become `[未译: OriginalTerm]`.
4. Preserve citation keys and footnote markers exactly.
5. Direct quotations: keep the original-language quotation verbatim and follow it with `（譯：……）`. Never replace the original with the translation.
6. Bind each quotation to `source_id`, exact corpus locator, and a Chicago author-date reference rendered with `shutong_citation` action `render`; confirm with `shutong_verify` and check the exact match with `shutong_analysis` mode `quotation`.
7. Return the translation with its exact corpus locator, confidence and citation.
8. Report notes written, glossary hits, `[未译]` terms, and any quotation whose original text did not match the corpus.
