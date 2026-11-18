---
description: Audit corpus Merkle integrity. Usage: /verify [csl_id] or /verify all
agent: verifier
---

Verify corpus integrity: $ARGUMENTS

If $ARGUMENTS is empty or "all": call `shutong_verify` with `mode: all`. Otherwise call `shutong_verify` with `mode: node`.
