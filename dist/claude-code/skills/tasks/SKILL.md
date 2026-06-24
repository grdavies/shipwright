---
name: sw-tasks
description: Generate a frozen task list from a frozen PRD using the spec union in a single pass without user-intervention gates.
---

# Task list generation (`/sw-tasks`)

Port of v1 `spec-tasks` under `sw-`. Reads U8 union so amended requirements are reflected.

## Path

`docs/prds/<n>-<slug>/tasks-<n>-<slug>.md` per `.sw/layout.md`.

## Procedure

1. Require frozen PRD as input.
2. Load effective spec via `scripts/spec-union.sh` or `skills/spec-union/SKILL.md`.
3. In **one pass**, identify parent tasks (phases) and expand each into `- [ ]` sub-tasks with **executable shape** (IM6):
   - Parent tasks: numbered, scoped, dependency-ordered, S/M/L sizing.
   - Sub-tasks: **File**, **Expected**, **R-IDs** as below.
   - Relevant Files + Notes as needed.
4. Add `## Traceability` table mapping each union R-ID → task ref → named test scenario.
5. Save task file; run `spec-rigor-check.sh` (tasks) + `traceability-check.sh`; freeze via `/sw-freeze`.
6. Register/refresh PRD entry in `docs/prds/INDEX.md` with status `not-started`.
7. **Stop** — do not start implementation. Standalone `/sw-tasks` ends after freeze; `doc.afterTasks` on
   `/sw-doc` owns the boundary to implementation.

## Executable sub-task shape

```markdown
- [ ] 1.1 Add tdd-gate script (R1)
  - **File:** `scripts/tdd-gate.sh`
  - **Expected:** JSON verdict on stdout; exit 0 pass, 20 fail
  - **R-IDs:** R1
```

Parent phase items (`1.`, `2.`) may remain summary-level; **numbered sub-tasks** (`1.1`, `1.2`) carry File +
Expected for `/sw-execute` plan-self-review.

## Collision policy

- **First run:** create the complete task file (parents, sub-tasks, traceability) in one pass.
- **Resume (unfrozen draft):** continue in the same file; do not duplicate sections.
- **Re-run against frozen task list:** require explicit confirmation before full overwrite.
- No sub-task-expansion gate — the human checkpoint between doc and implementation is `doc.afterTasks`
  (orchestrator boundary), not `/sw-tasks`.

## Handoff

→ implementation workstream (`/sw-execute` when available) only after the doc orchestrator boundary (`doc.afterTasks`).
