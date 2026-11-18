---
name: analysis-plan
description: Scope a paper text-analysis question, source selection, language handling and validation method before computation.
---

The main agent owns the analysis brief with the scholar. Record the question, explicit paper_id and source_ids, comparison units, language, method, parameters and validity checks. Ask only about choices that materially change the interpretation. Do not switch the active work without confirmation.

Bibliographer proposes relevant texts, editions/translations, contextual and opposing scholarship, and coverage gaps using public metadata. Save candidates through `shutong_bibliography`; metadata annotations must not imply full-text reading. Obtain scholar approval and authorized ingestion before analysis. Noter identifies the passage-level method; Verifier checks the resulting evidence.

Choose `shutong_analysis` action `run`, mode `concordance`, `collocations`, `contextual_sentiment`, `quotation` or `text_reuse`. The first release supports language `en` or `zh`; Han characters are individual units, not linguistically segmented words. Agree on normalization and source/edition comparisons before interpreting counts. Contextual sentiment requires a written rubric and an attitude target; source reuse requires at least two sources.

Methods are local and bounded. Do not infer significance from raw counts, calculate imaginary statistics, or claim that matching phrases prove borrowing. If the requested method is unsupported, explain the gap instead of substituting it silently.
