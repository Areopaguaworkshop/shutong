---
name: workspace-planner
description: Route a scholar's request to a confirmed project and work without mixing evidence.
---

Use this skill when a request may begin, resume, compare, or switch a paper, chapter, book, or research project.

1. Call shutong_workspace with action `plan_switch` and the new request.
2. Present its local-metadata recommendation. Do not activate another workspace automatically.
3. After explicit scholar confirmation, call shutong_workspace with action `activate` and confirmed: true.
4. For a book, create the project first, then its chapter works. Chapters share the project bibliography and ingested sources; notes, claims, audits, and drafts stay work-local.
5. Do not reuse a note or claim in another work without an explicit transfer and fresh verification there.
