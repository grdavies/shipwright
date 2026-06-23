---
description: Commit the current phase after verify and review. Does not push or open a PR.
alwaysApply: false
---

# `/pf-commit`

Phase-scoped commit after `/pf-verify` (and `/pf-review` when configured).

## Procedure

1. Confirm `/pf-verify` passed.
2. Complete `/pf-review` when review is enabled; address actionable findings.
3. `memory-preflight` checkpoint for durable learnings (redact before store).
4. Review delta; stage only phase files.
5. **Exclude** per-worktree state (`phase-flow.json`), memory-sync markers, provider cache.
6. Commit with heredoc message matching repo style.
7. Hand off to `/pf-pr`.

## Guardrails

- No unrelated dirty-tree files.
- Never commit `phase-flow.json` or `.git/phase-flow-memory-sync.json`.
- Does not push or open PR.
