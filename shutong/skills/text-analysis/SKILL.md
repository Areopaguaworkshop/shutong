---
name: text-analysis
description: Use Noter's paper-scoped tools for concordance, collocations, contextual sentiment, exact quotation checks and source text reuse.
---

Noter performs analysis through `shutong_analysis`; shell access is unnecessary. Use only explicitly selected, approved, ingested paper sources. Do not send source passages to an external analysis API.

Run with `action: run`, `paper_id`, `source_ids`, `question`, `language: en|zh` and `mode`. For all modes except `text_reuse`, include `query`. Each run saves an analysis_id and returns record_sha256, method, parameters, source hashes/CSL, results, limitations and pending review. `action: get` with paper_id and analysis_id retrieves it and checks whether sources changed.

- `concordance`: token-sequence matches with exact source spans and left/right context. `context` is characters (20–1000); `limit` caps returned examples (1–200), not occurrence counts.
- `collocations`: `window` is 1–20 tokens on each side of each target occurrence, inside the same node. Report counts, document frequencies and corpus/target totals. A token can be counted for multiple nearby targets. No association significance is computed.
- `contextual_sentiment`: provide `rubric`; retrieve contexts first. Interpret speaker, target, negation, reported speech and context using that rubric. Preserve mixed/uncertain cases. Save labels through `action: annotate`, with paper_id, analysis_id, current record_sha256, actual model_id and annotations containing context_index (zero-based), target, speaker, label (`favorable|unfavorable|neutral|mixed|uncertain`), rationale and confidence (`known|probable|speculative`). Annotation replaces the current annotation set and resets review. Missing context is not neutral sentiment. No numerical sentiment score or automatic classifier is supplied.
- `quotation`: exact case-sensitive characters in the ingested text. Use returned source_id, node_id, page/section and start/end offsets. A mismatch requires inspection; do not quietly normalize or alter a quotation.
- `text_reuse`: `minimum_tokens` is 4–30; finds equal NFC/casefolded token sequences across different sources, ignoring punctuation. Return both passage locations. It is not fuzzy matching, a plagiarism finding or proof of literary dependence. The older private-note overlap helper is a different operation.

English uses Unicode word units; Han text uses individual characters. No stemming or Chinese word segmentation is performed. Runs stop above 50 sources, 5000 nodes, 2 million characters, or 200000 reuse windows; request a narrower source set. Report all truncation and node-boundary limitations. Never call a limited sample exhaustive.

Report the inspected result with its analysis ID, source ID, exact locator and cited passage.
