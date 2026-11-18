---
description: Run the full research→publication pipeline. Use for end-to-end research, paper writing, or review.
---

Run the stages yourself, in order, through the MCP tools. There is no pipeline
tool and no `pipeline_id`; the backend keeps the state.

1. `research` — `shutong_search`, then `shutong_verify` on every cited passage.
   Exclude failures.
2. `outline` — the host agent writes the outline from citable corpus passages.
3. `draft` — only after `shutong_paper_audit` reports every stage present, and
   only on an explicit scholar request. Draft from cited corpus passages.
4. `style` — apply the paper's citation style with `shutong_citation` action
   `render`.
5. `quality` — `shutong_verifier_report` action `record` with inspected evidence.
6. `review` — `shutong_analysis` actions `run` and `review` where analysis backs
   a claim.

Stop at the first missing gate and tell the scholar which stage blocks the draft.
Never describe a stage as complete without the tool result that proves it.
