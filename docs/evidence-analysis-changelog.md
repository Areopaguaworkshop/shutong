# Evidence analysis implementation changelog

## 2026-09-10 — work started

- Recorded the authorized plan in `docs/plans/2026-09-10-evidence-analysis-plan.md`.
- Asked the scholar about language coverage, sentiment behavior and approximate matching.
- Preserving the earlier package-privacy changes and workflow artifacts.
- In progress: inspect corpus loading, integrity verification, paper artifacts and host rendering before implementation.
- Validation: not yet run for this feature.

## 2026-09-10 — backend and skill implementation

- Working defaults (clarifications still pending): English/Chinese; Unicode words plus explicit Han character units; rubric-based sentiment; exact normalized token-sequence reuse.
- Added `analysis.py` operations and paper-local analysis records with source hashes, locations, parameters, annotations and review provenance.
- Added `shutong_analysis` to MCP and the Bun tool registry; the public surface now has 26 tools. Existing RPC `tool_call` remains the transport.
- Analysis-linked notes require a current passing review; changed sources or revised reviewed records block downstream evidence use.
- Authored four focused skills under the packaged Python templates; host rendering integration is next.
- Validation: implementation is not yet accepted; synthetic tests and package inspection remain pending.

## 2026-09-10 — validation complete

- Completed canonical skill loading and role routing for all five host renderers, preserving existing user files. Python project templates expose the same four skill texts.
- Retained the stated defaults after the scholar requested continuation: English/Chinese character units, rubric-based sentiment interpretation, exact normalized source reuse. No additional subagent or NLP dependency was added.
- Backend: **96 tests passed** across `test_analysis.py`, `test_papers.py` and `test_mcp_tools.py`. Coverage includes public dispatch, paper/source boundaries, corrupted and stale evidence, counts, offsets, ambiguous annotations and downstream note/claim/draft gates.
- Bun: **29 tests passed, 191 assertions**; `bun run --cwd shutong typecheck` passed. Tests cover all five hosts, valid Codex TOML, skill parity, preservation of custom files and package privacy fixtures.
- Diagnosed the earlier asynchronous stall: a minimal `asyncio.to_thread` operation hung inside the sandbox and completed outside it. The bounded backend suite passed outside the sandbox. No application workaround was introduced. Eleven existing DSPy deprecation warnings remain.
- All four skills passed the skill-creator validator; Python-generated skill contents matched canonical files.
- Actual `bun pm pack`: **114 runtime files, 159,728 bytes**. Every archive member matched the runtime allowlist; no hidden files or symlinks were present. The analysis module and four skills were included; runtime catalog dependencies were resolved. Receipt: [package audit](artifacts/evidence-analysis-package-audit.json).
- Added the [usage guide](evidence-analysis.md) with review flow, API examples, method limits and host restart/update guidance. Updated the plan checklist and README.
- Completion applies to this bounded analysis feature and packaging checks. No registry publication, personal corpus analysis or forced host configuration overwrite was performed. It does not certify autonomous whole-paper quality or resolve unrelated architecture backlog items.
- Known limits: no approximate reuse, linguistic Chinese segmentation or automatic sentiment scoring; review identity remains supplied metadata; callers must serialize updates to an analysis record across processes.
