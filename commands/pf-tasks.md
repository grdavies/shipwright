---
description: Generate a frozen task list from a frozen PRD with mandatory Go gate before sub-task expansion. Does not start implementation.
alwaysApply: false
---

# `/pf-tasks`

Task list from frozen PRD + amendment union.

## Scope

- Input: frozen PRD path.
- Output: `docs/prds/<n>-<slug>/tasks-<n>-<slug>.md` (frozen via `/pf-freeze`).
- Does **not** start implementation or reconcile git-derived index status.

## Procedure

1. Verify PRD has `frozen: true`.
2. Load `skills/tasks/SKILL.md`.
3. Read effective requirements via `scripts/spec-union.sh <prd-path>`.
4. Draft parent tasks; **pause for "Go"** before sub-task expansion.
5. After user confirms "Go", expand sub-tasks, Relevant Files, Notes.
6. Add **`## Traceability`** table: every union R-ID → task ref → named test scenario (see `skills/spec-rigor/SKILL.md`).
7. Save; run spec-rigor + traceability gates, then `/pf-freeze` on task list.
8. Update `docs/prds/INDEX.md` entry (status `not-started`).

## Guardrails

- Go gate is mandatory — no sub-tasks until user confirms.
- Task list reflects union, not bare parent alone.
- Traceability table required — `traceability-check.sh` blocks freeze on uncovered R-IDs.
- Git-derived index reconciliation is owned by `003`.
