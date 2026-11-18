---
name: citation-check
description: Verify quotations, citation metadata and analysis-backed claim support independently before a paper report is used.
---

Verifier owns the audit. Bibliographer supplies bibliographic metadata; the main agent corrects its own prose. Keep three decisions separate: source integrity, exact quotation agreement, and whether the passage supports the claim.

Use `shutong_verify` for integrity, `shutong_citation` actions `resolve`/`render` for metadata and formatted references, and `shutong_analysis` mode `quotation` for exact ingested-text matches within explicit paper source_ids. For direct quotes compare text and locator against the source; an exact extracted-text match does not certify an OCR transcription against the page image. Check in-text citations against the reference list, distinguish editions and translated quotations, and flag ambiguous or missing metadata.

For analysis results, call `shutong_analysis` action `get`; inspect method, parameters, hashes, exact spans, count denominators, truncation, annotation rubric and model identity. Independently check representative computations and decision-bearing interpretations. Never turn uncertainty into pass, claim an unperformed rerun, or treat a local Merkle pass as semantic truth.

Record `action: review` with paper_id, analysis_id, the exact current record_sha256, outcome (`pass|fail|uncertain`), reviewer identity and evidence describing inspected results and limitations. This stores a supplied review; it does not authenticate reviewer independence. Only then verify analysis-backed notes through `shutong_note` and claims through `shutong_claim`. Source changes or revised annotations require a fresh review and affected notes must be recreated/reverified. Do not rewrite the audited analysis as the verifier.
