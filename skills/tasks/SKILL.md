---
name: pf-tasks
description: Generate a frozen task list from a frozen PRD using the spec union, with mandatory Go gate before sub-task expansion.
---

# Task list generation (`/pf-tasks`)

Port of v1 `spec-tasks` under `pf-`. Reads U8 union so amended requirements are reflected.

## Path

`prds/<n>-<slug>/tasks-<n>-<slug>.md` per `docs/layout.md`.

## Procedure

1. Require frozen PRD as input.
2. Load effective spec via `scripts/spec-union.sh` or `skills/spec-union/SKILL.md`.
3. Identify parent tasks (phases): numbered, scoped, dependency-ordered, S/M/L sizing.
4. **Pause:** "Respond with 'Go' to generate sub-tasks." — mandatory.
5. After "Go", expand each parent into `- [ ]` sub-tasks with **executable shape** (IM6):
   - **File:** exact path(s) to create or modify
   - **Expected:** observable outcome (command output, API shape, test name)
   - **R-IDs:** requirement IDs covered
   - Relevant Files + Notes as needed
6. Add `## Traceability` table mapping each union R-ID → task ref → named test scenario.
7. Save task file; run `spec-rigor-check.sh` (tasks) + `traceability-check.sh`; freeze via `/pf-freeze`.
8. Register/refresh PRD entry in `prds/INDEX.md` with status `not-started`.

## Executable sub-task shape

```markdown
- [ ] 1.1 Add tdd-gate script (R1)
  - **File:** `scripts/tdd-gate.sh`
  - **Expected:** JSON verdict on stdout; exit 0 pass, 20 fail
  - **R-IDs:** R1
```

Parent phase items (`1.`, `2.`) may remain summary-level; **numbered sub-tasks** (`1.1`, `1.2`) carry File +
Expected for `/pf-execute` plan-self-review.

## Collision policy

- First run: create parents, pause for Go.
- Resumed Go: expand same file; do not duplicate.
- Full overwrite: confirm first.

## Handoff

→ implementation workstream (`/pf-execute` when available).
