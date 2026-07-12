---
name: tasks
description: Generate a frozen task list from a frozen PRD using the spec union in one pass. Use when PRD is frozen and implementation tasks are needed before /sw-freeze. No mid-pass user gates; does not implement.
---
# Task list generation (`/sw-tasks`)

Port of v1 `spec-tasks` under `sw-`. Reads U8 union so amended requirements are reflected.


**Model tier:** deep — resolve via `python3 scripts/resolve-model-tier.py --skill tasks`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).


## Issue-store authoring (PRD 056 R11–R12)

When effective backend is `issue-store`:

1. **Never** write task lists under `docs/prds/` in the code repo.
2. Persist via `planning_store.put` with unit id `tasks-<n>-<slug>` and virtual body-path `docs/prds/<n>-<slug>/tasks-<n>-<slug>.md`.
3. Run gates on handles (materialize is deliver-time only):

   ```bash
   python3 scripts/spec-rigor-check.py --artifact tasks --path <body-path> --unit-id <tasks-unit-id>      --prd <prd-body-path> --prd-unit-id <prd-unit-id>
   python3 scripts/traceability-check.py --prd <prd-body-path> --tasks <body-path> [--prd-unit-id …] [--tasks-unit-id …]
   ```

4. INDEX registration is mechanical reconcile / living-docs — not a local `docs/prds/INDEX.md` write.

File-store repos: unchanged — path and file save below apply.

## Path

`docs/prds/<n>-<slug>/tasks-<n>-<slug>.md` per `.sw/layout.md`.

## Procedure

1. Require frozen PRD as input.
2. Load effective spec via `scripts/spec-union.py` or `skills/spec-union/SKILL.md`.
3. In **one pass**, identify parent tasks (phases) and expand each into `- [ ]` sub-tasks with **executable shape** (IM6):
   - Parent tasks: numbered, dependency-ordered, `small|medium|large` sizing from the deterministic heuristic (`### N.` headings; see **Phase sizing heuristic** below).
   - Sub-tasks: **File**, **Expected**, **R-IDs** as below.
   - Relevant Files + Notes as needed.
   - **Prefer many small phases** with explicit `## Phase Dependencies` edges over few large sequential phases (R19).
4. Emit **`## Phase Dependencies`** (required) — machine-parseable edge source for `/sw-deliver` phase-mode (R5/R6/R37). Place after `## Tasks` and before `## Traceability`.
5. Run execute-tier granularity pass (see **Execute-tier granularity** below).
6. Add `## Traceability` table mapping each union R-ID → task ref → named test scenario → **ZOMBIES checklist** (test-list-first; see `skills/spec-rigor/references/zombies.md`).
7. Save task file; run `spec-rigor-check.py` (tasks) + `traceability-check.py`; freeze via `/sw-freeze`.
8. Register/refresh PRD entry in `docs/prds/INDEX.md` with status `not-started`.
9. **Stop** — do not start implementation. Standalone `/sw-tasks` ends after freeze; `doc.afterTasks` on
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

### Deliver-time fallback (PRD 013 — legacy lists only)

**Sequential fallback (R8):** when neither declared edges nor file-set inference apply, deliver assigns strict sequential edges with a notice.

`/sw-tasks` **requires** `## Phase Dependencies` at freeze (`spec-rigor-check.py` blocks missing/invalid tables).
For **legacy** frozen lists that omit the table, `/sw-deliver` applies the PRD 013 ladder (authoritative in
`skills/deliver/SKILL.md`):

1. **Declared** — explicit `## Phase Dependencies` rows (always preferred at authoring time).
2. **File-set inference** — overlapping `**File:**` paths infer serializing edges before wave assignment.
3. **Sequential + notice** — strict `1→2→3…` edges with a missing-edges notice when inference finds no overlap.

Authors MUST emit explicit edges for new task lists — never rely on deliver-time fallback for multi-phase PRDs.

## Phase sizing heuristic (PRD 040)

Replace informal S/M/L labels with the deterministic scorer:

```bash
python3 scripts/phase_sizing.py score docs/prds/<n>-<slug>/tasks-<n>-<slug>.md
python3 scripts/phase_sizing.py advisory docs/prds/<n>-<slug>/tasks-<n>-<slug>.md   # draft-only block
```

Per phase the scorer emits `size: small|medium|large` from structural signals (`filesTouched`,
`traceabilityScenarios`, `depFanOut`, `subTaskCount`, `distinctDirs`) against `tasks.sizing.thresholds` in
config. Thresholds and bounds (`minPhaseFiles`, `minPhaseScenarios`, `maxPhaseCount`) are documented in
`core/sw-reference/phase-sizing.schema.json`.

### Small-phase design constraint (R18)

**Small phases are a design constraint** for reviewability and wave parallelism (Osmani on bounded change sets;
Faros reports on agent PR size). Each phase SHOULD stay `small` or `medium` where practical. Splitting below the
**minimum-viable-phase floor** (`belowFloor: true`) is not rewarded — avoid granularity DoS (many tiny phases
inflating merge-gate load).

### Prefer-many-small + split suggestions (R19)

- Prefer **many small phases with declared dependency edges** over one large sequential phase.
- When `overThreshold: true` or `separableSets` has multiple components, review the advisory split suggestion
  (draft-only; stripped at freeze). Each proposed edge MUST respect contention families documented in
  `skills/parallelism/SKILL.md` (shared migrations, living INDEX/numbering, `CHANGELOG`/`version.txt`,
  `**File:**` overlap, generator-output / golden-manifest globs).
- Adopting a split requires an unfrozen `/sw-tasks` re-run + `/sw-freeze` — never edit a frozen task list in place.

## Executable sub-task shape

```markdown
- [ ] 1.1 Add tdd-gate script (R1)
  - **File:** `scripts/tdd-gate.py`
  - **Expected:** JSON verdict on stdout; exit 0 pass, 20 fail
  - **R-IDs:** R1
```

Parent phase items (`1.`, `2.`) may remain summary-level; **numbered sub-tasks** (`1.1`, `1.2`) carry File +
Expected for `/sw-execute` plan-self-review.


## Execute-tier granularity (PRD 055 R16–R20)

Every generated task list MUST include bounded intra-phase sub-task refs sized for PRD 053 execute-tier
fan-out. This is a **first-class generation requirement** alongside `## Phase Dependencies` and
`## Traceability`.

### Authoring procedure

After drafting sub-tasks and before `/sw-freeze`:

```bash
python3 scripts/tasks_generate.py apply-granularity --task-list docs/prds/<n>-<slug>/tasks-<n>-<slug>.md --inplace
python3 scripts/tasks_generate.py check --task-list docs/prds/<n>-<slug>/tasks-<n>-<slug>.md
```

`apply-granularity` decomposes list-shaped `**File:**` fields (comma/and-separated paths, glob lists)
into one ref per bounded file-set when contention rules permit parallelism. It emits a durable
`## Execute-tier granularity` section with split preflight JSON — part of the frozen artifact, **not**
the advisory-only `## Sizing & Split Suggestions` block stripped at freeze.

Re-numbering: when a ref splits (e.g. `3.1` → three units), refs within the phase are renumbered in order
(`3.1`, `3.2`, `3.3`, …) preserving phase-local sequence.

### Contention and serial edges

When `phase_sizing.separable_sets_for_paths()` groups paths into one contention family, parallelism is
forbidden — `apply-granularity` documents serial edges in the `## Execute-tier granularity` JSON rather
than emitting parallel refs.

### Runtime escape hatch (R20)

**Already frozen** coarse lists are never mutated. `execute_plan.py` runtime expansion remains the
sanctioned fallback for in-flight deliver runs until the task list can be re-generated.


## Blocking sizing freeze gate (PRD 065 R16)

At `/sw-freeze`, `spec-rigor-check.py` runs the **blocking** sizing gate (`phase_sizing.py
`evaluate_freeze_gate`):

- Over-threshold phases **block freeze** with split suggestions (same scorer as `phase_sizing.py score`).
- Advisory `## Sizing & Split Suggestions` blocks are stripped before freeze — they do not satisfy the gate.
- **Human override only** — durable record at `.cursor/sw-sizing-overrides/<key>.json` with `actor`,
  `reason`, and `overThresholdPhases`. Agents on autonomous `/sw-doc` → `/sw-tasks` dispatch cannot author
  overrides (`refuse_autonomous_override`).
- Deliver-time sizing report (`/sw-deliver --sizing-report`) is read-only visibility — it does not bypass
  the freeze gate.

## Collision policy

- **First run:** create the complete task file (parents, sub-tasks, phase dependencies, traceability) in one pass.
- **Resume (unfrozen draft):** continue in the same file; do not duplicate sections.
- **Re-run against frozen task list:** require explicit confirmation before full overwrite.
- No sub-task-expansion gate — the human checkpoint between doc and implementation is `doc.afterTasks`
  (orchestrator boundary), not `/sw-tasks`.

## Handoff

→ implementation workstream (`/sw-execute` when available) only after the doc orchestrator boundary (`doc.afterTasks`).
