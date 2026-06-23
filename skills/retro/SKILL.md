---
name: pf-retro
description: Post-ship retrospective — what went well/painful/change; learning candidates for compounding. Report-only by default.
---

# Retrospective

Run after a human merge (or at end of `/pf-ship` merge gate when user merges).

## Procedure

1. `git log --oneline -20` on shipped branch / merged PR.
2. Identify: went well, painful, process changes.
3. Compare against memory + doctrine (read-only unless user approves edits).
4. Output **distilled learning candidates** for `/pf-compound` — no raw transcripts.
5. Run output through `scripts/memory-redact.sh` before any persistence.

## Guardrails

- Report-only — no `agentsFile`/doctrine edits without approval.
- No secrets or verbatim transcripts in output.
- Does not auto-write memory (hand off to `/pf-compound`).
