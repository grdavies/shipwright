---
description: Execute one phase-sized slice on the current branch using the spec union. Does not commit, push, or open a PR.
alwaysApply: false
---

# `/pf-execute`

Implement exactly one planned phase on the current branch inside the worktree.

## Procedure

1. Load the task file from `tasksDir` for this phase; resolve requirements via **spec union**:

   ```bash
   bash scripts/spec-union.sh <frozen-prd-path>
   ```

   Load `skills/spec-union/SKILL.md`. Amended/superseded requirements win over bare parent PRD.
2. Verify branch matches `scripts/phase-state.sh read` → `currentBranch`.
3. `memory-preflight` read: PRD/task, target files, prior learnings.
4. Load `agentsFile` + applicable doctrine.
5. `TodoWrite` for the phase checklist items.
6. Implement the slice; keep todos and task file checkboxes current.
7. Optional issue comments when `issueNumbers` set (`gh issue comment`).
8. `memory-preflight` write for durable decisions only (redact via `scripts/memory-redact.sh` first).
9. Subagents per `rules/pf-subagent-dispatch.mdc` for independent parallel work.
10. Leave uncommitted for `/pf-verify`, `/pf-review`, `/pf-commit`.

## Guardrails

- One phase per invocation; read spec union, not bare parent PRD alone.
- Per-worktree state is authoritative for parent/phase context.
- Does not push or open PR.
