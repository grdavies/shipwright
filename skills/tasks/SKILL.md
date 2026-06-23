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
5. After "Go", expand each parent into `- [ ]` sub-tasks + Relevant Files + Notes.
6. Save task file; freeze via `/pf-freeze`.
7. Register/refresh PRD entry in `prds/INDEX.md` with status `not-started`.

## Collision policy

- First run: create parents, pause for Go.
- Resumed Go: expand same file; do not duplicate.
- Full overwrite: confirm first.

## Handoff

→ implementation workstream (`/pf-execute` when available).
