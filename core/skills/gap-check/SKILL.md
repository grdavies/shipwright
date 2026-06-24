---
name: sw-gap-check
description: Compare phase plan (spec union + task checklist) against git diff; bounded closers for in-scope gaps. Default-on in /sw-ship.
---

# gap-check

Catches planned vs actual before commit.

## Inputs

- **Plan:** task checklist for `phaseSlug` in `tasksDir` + spec union (`scripts/spec-union.sh <prd>`).
- **Backlog:** open rows from `bash scripts/feedback-backlog.sh list --open-only` (`skills/feedback-closure/SKILL.md`) — map against diff when PR-linked.
- **Actual:** diff against per-worktree `parentBranch`:

```bash
PARENT=$(bash scripts/phase-state.sh read | jq -r .parentBranch)
git diff --stat "$PARENT"...HEAD
git diff "$PARENT"...HEAD
```

## Procedure

1. Load config + plan + diff + open backlog items.
2. Read-only subagent maps each checklist item → `done` | `partial` | `missing` + unplanned hunks.
3. Gap report table.
4. In-scope gaps → bounded closer subagents (one gap each); re-verify.
5. Ambiguous/out-of-scope → escalate (toward feedback workstream `005`); never absorb silently.
6. Re-map once; escalate residuals.

## Modes

- **Default (`/sw-ship`):** after execute; `--fast` skips.
- **Standalone (`/sw-gaps`):** same; `--report-only` never mutates.

## Guardrails

- Mapping before closers.
- Closers bounded — no scope expansion.
- Spec union is the requirement source, not bare parent PRD.
