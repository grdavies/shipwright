---
description: Generate a frozen task list from a frozen PRD in a single pass. Does not start implementation.
alwaysApply: false
---

# `/sw-tasks`

Task list from frozen PRD + amendment union.

## Scope

- Input: frozen PRD path.
- Output: `docs/prds/<n>-<slug>/tasks-<n>-<slug>.md` (frozen via `/sw-freeze`).
- Does **not** start implementation or reconcile git-derived index status.

## Procedure

1. Verify PRD has `frozen: true`.
2. Load `skills/tasks/SKILL.md`.
3. Read effective requirements via `scripts/spec-union.sh <prd-path>`.
4. In **one pass**, draft parent tasks (phases), expand executable sub-tasks, Relevant Files, and Notes.
5. Add **`## Traceability`** table: every union R-ID → task ref → named test scenario (see `skills/spec-rigor/SKILL.md`).
6. Save; run spec-rigor + traceability gates, then `/sw-freeze` on task list.
7. Update `docs/prds/INDEX.md` entry (status `not-started`).
8. **Stop** — standalone runs end here without implementation. The human checkpoint between documentation
   and implementation is `doc.afterTasks` on `/sw-doc` (or `--after-tasks` on `/sw-ship`), not a gate inside
   `/sw-tasks`.

## Guardrails

- Single-pass generation — complete list (parent phases, executable sub-tasks, traceability) with no
  user-intervention gate.
- Overwrite of an existing **frozen** task list still requires explicit confirmation before replacing.
- Task list reflects union, not bare parent alone.
- Traceability table required — `traceability-check.sh` blocks freeze on uncovered R-IDs.
- Does not provision worktrees or run `/sw-execute`.
