---
name: sw-tasks
description: Generate a frozen task list from a frozen PRD using the spec union in a single pass without user-intervention gates.
---

# Task list generation (`/sw-tasks`)

Port of v1 `spec-tasks` under `sw-`. Reads U8 union so amended requirements are reflected.


**Model tier:** deep — resolve via `python3 scripts/resolve-model-tier.sh --skill tasks`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## Path

`docs/prds/<n>-<slug>/tasks-<n>-<slug>.md` per `.sw/layout.md`.

## Procedure

1. Require frozen PRD as input.
2. Load effective spec via `scripts/spec-union.sh` or `skills/spec-union/SKILL.md`.
3. In **one pass**, identify parent tasks (phases) and expand each into `- [ ]` sub-tasks with **executable shape** (IM6):
   - Parent tasks: numbered, dependency-ordered, S/M/L sizing (`### N.` headings).
   - Sub-tasks: **File**, **Expected**, **R-IDs** as below.
   - Relevant Files + Notes as needed.
4. Emit **`## Phase Dependencies`** (required) — machine-parseable edge source for `/sw-deliver` phase-mode (R5/R6/R37). Place after `## Tasks` and before `## Traceability`.
5. Add `## Traceability` table mapping each union R-ID → task ref → named test scenario.
6. Save task file; run `spec-rigor-check.sh` (tasks) + `traceability-check.sh`; freeze via `/sw-freeze`.
7. Register/refresh PRD entry in `docs/prds/INDEX.md` with status `not-started`.
8. **Stop** — do not start implementation. Standalone `/sw-tasks` ends after freeze; `doc.afterTasks` on
   `/sw-doc` owns the boundary to implementation.

## Phase Dependencies table (required)

Every generated task list MUST include a `## Phase Dependencies` section with this table shape (parsed by
`scripts/wave_deliver.py` in `/sw-deliver` phase-mode):

```markdown
## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 1 |
| 4 | 2, 3 |
```

Rules:

- **One row per phase** (`### N.` parent in `## Tasks`). Phase column is the integer `N` only.
- **Depends on** is `none`, a single phase number, or comma-separated phase numbers (e.g. `2, 5`).
- Edges are authoritative for `/sw-deliver` wave planning — derive from the dependency order of parent phases.
- Human-reviewable; lives inside the task-list artifact (no sidecar file).

### Sequential fallback (R8)

If a task list omits `## Phase Dependencies`, `/sw-deliver` falls back to strict sequential edges (`2:1`, `3:2`, …)
with **no parallelism** and emits a missing-edges notice. Authors SHOULD emit explicit edges whenever phases can
run in parallel or have non-linear dependencies — do not rely on sequential fallback for multi-phase PRDs.

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

- **First run:** create the complete task file (parents, sub-tasks, phase dependencies, traceability) in one pass.
- **Resume (unfrozen draft):** continue in the same file; do not duplicate sections.
- **Re-run against frozen task list:** require explicit confirmation before full overwrite.
- No sub-task-expansion gate — the human checkpoint between doc and implementation is `doc.afterTasks`
  (orchestrator boundary), not `/sw-tasks`.

## Handoff

→ implementation workstream (`/sw-execute` when available) only after the doc orchestrator boundary (`doc.afterTasks`).
