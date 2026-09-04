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

## Freeze ownership under doc-loop (PRD 081 R10)

| Context | Freeze behaviour |
| --- | --- |
| **Standalone** `/sw-tasks` | **Freeze-by-default** — step 10 always invokes `/sw-freeze` on the task list before stopping |
| **Doc-loop driver** (`scripts/doc_loop.py`) | Task generation runs with **`noFreeze: true`** on the `tasks` step; the driver's `freeze-tasks` mechanical stage owns the single orchestrated freeze |
| **Related-work scan** | Moved to parent — `related-work` is a **doc-loop** stage before `freeze-prd`, not a gate inside `/sw-tasks` |

The orchestrated path records freeze **owner** (`doc-loop:<run-id>`) and receipt fields in durable
`artifactRevisions` — one freeze per artifact, no duplicate owner stamps.

### Migration note (callers of the old second-freeze path)

Callers that previously assumed `/sw-tasks` always froze the list **and** the doc orchestrator froze again
must not invoke `/sw-freeze` on the task list after a doc-loop `tasks` step:

- **`/sw-doc` doc-loop path** — rely on `freeze-tasks` only; a direct `/sw-freeze` after driver `tasks`
  duplicates ownership and may fail spec-rigor on already-frozen artifacts.
- **`/sw-ship --after-tasks`** entering implementation without `/sw-doc` — unchanged: standalone
  `/sw-tasks` still freezes at step 10.
- **Issue-store materialize** — `planning_store.verify-frozen-hash` remains authoritative; missing driver
  freeze receipts fail deliver entry closed.

Environment: `SW_DOC_DRIVER=1` / `SW_DOC_ORCHESTRATOR=1` sets `driverInvoked` on freeze receipts
(`scripts/check_frozen_lib.py`).

Doc-loop concurrency for the parent run index and cross-clone handoff locks is documented under
`/sw-doc` **Durable doc-run driver** and `.shipwright/layout.md` (PRD 090 R1/R2) — `/sw-tasks` inherits those
guards when invoked as the doc-loop `tasks` stage with `noFreeze: true`.

## Procedure

0. **Authoring-guard preflight (PRD 032 R5/R14)** — before the first substantive mutation on a planning unit, run `python3 scripts/authoring-guard.py preflight --path <unit-artifact> --command sw-tasks`; on a genuinely in-flight unit, pass `--handoff <reason>` instead of mutating (R6).
1. Verify PRD has `frozen: true`.
2. Load `skills/tasks/SKILL.md`.
3. Read effective requirements via `scripts/spec-union.py <prd-path>`.

   - **Backlog re-scan (R2):** before drafting tasks, run
     `python3 scripts/planning-related.py scan --mode tasks-rescan --path <prd-path>`; propose PRD amendments
     for newly-related items; human confirms via `planning-related.py confirm`. Edge materialization remains
     autonomous via the PRD 033 reconciler **after** confirmed choices only (R3).
   - **Orchestrated short-circuit (R11):** when the doc-loop `tasks` step includes an orchestrated receipt
     (`orchestrated: true`, `relatedWorkResolved: true`, `parentRunId: <doc-run-id>`) because the parent run's
     `related-work` stage already resolved, pass `--orchestrated --parent-run-id <doc-run-id>` to
     `planning-related.py scan` instead of re-running the rescan — doc-loop-orchestrated runs get exactly one
     related-work checkpoint, not two. Standalone `/sw-tasks` invocations omit these flags and run the rescan
     unchanged.
4. In **one pass**, draft parent tasks (phases), expand executable sub-tasks, Relevant Files, and Notes.
5. Add **`## Phase Dependencies`** table: `| Phase | Depends on |` with one row per phase (`none` or phase refs); machine-parseable by `/sw-deliver` (R5/R6/R37).
6. Run **`python3 scripts/tasks_generate.py apply-granularity --task-list <task-list> --inplace`** then **`python3 scripts/tasks_generate.py check --task-list <task-list>`** — execute-tier granularity is required alongside Phase Dependencies and Traceability (R16–R18).
7. Add **`## Traceability`** table: every union R-ID → task ref → named test scenario → **ZOMBIES checklist** column (see `skills/spec-rigor/references/zombies.md`).
8. Save; run spec-rigor + traceability gates; when `planning.visibilityProfile` is `all-private`, run
   `python3 scripts/planning_visibility.py check-freeze-visibility <task-list>` before `/sw-freeze`.
9. **Blocking sizing freeze gate (PRD 065 R16)** — `spec-rigor-check.py` invokes
   `phase_sizing.py evaluate_freeze_gate` before freeze. Any phase over configured thresholds blocks freeze
   with split suggestions unless a **human-attributed** override exists at
   `.cursor/sw-sizing-overrides/<task-list-key>.json` (`actor` + `reason` required). Autonomous dispatch paths
   (`/sw-doc` → `/sw-tasks`) refuse agent-set overrides (`phase_sizing.py refuse_autonomous_override`).
10. `/sw-freeze` on task list.
11. Update `docs/prds/INDEX.md` entry (status `not-started`).
12. **Stop** — standalone runs end here without implementation. The human checkpoint between documentation
   and implementation is `doc.afterTasks` on `/sw-doc` (or `--after-tasks` on `/sw-ship`), not a gate inside
   `/sw-tasks`.

**Communication intensity:** lite

**Model tier:** deep — resolve via `python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --command sw-tasks`.

## Guardrails

- **Complete-unit refusal (R9):** mutations under a `status: complete` unit folder are rejected by the
  completed-unit immutability hook (`core/hooks/pre-commit-completed-unit.py`; see `/sw-freeze`).
- Single-pass generation — complete list (parent phases, executable sub-tasks, traceability) with no
  user-intervention gate.
- Overwrite of an existing **frozen** task list still requires explicit confirmation before replacing.
- Task list reflects union, not bare parent alone.
- Traceability table required — `traceability-check.py` blocks freeze on uncovered R-IDs.
- Execute-tier granularity required — `tasks_generate.py apply-granularity` before freeze; durable `## Execute-tier granularity` section (not advisory sizing block); `tasks_generate.py check` passes (R16–R18).
- Phase Dependencies table required — `spec-rigor-check.py` blocks freeze when missing or invalid (R5/R6/R37).
- Phase sizing uses the deterministic `small|medium|large` heuristic (`python3 scripts/phase_sizing.py score`);
  informal S/M/L labels are deprecated. Prefer many small phases with explicit dependency edges (R19).
- Small phases are a **design constraint** bounded by `tasks.sizing.minPhaseFiles` / `minPhaseScenarios` floor
  and `maxPhaseCount` cap (R18). Split suggestions cite contention families in `skills/parallelism/SKILL.md`.
- Legacy lists missing `## Phase Dependencies` at deliver time follow the PRD 013 ladder in `skills/deliver/SKILL.md`
  (declared → file-set inference → sequential+notice) — authors must still emit the table at freeze.
- Does not provision worktrees or run `/sw-execute`.

## Currency (PRD 085 R11)

When the parent doc-loop `tasks` stage carries an orchestrated receipt (`orchestrated`,
`relatedWorkResolved`, `parentRunId`), pass `--orchestrated --parent-run-id` to
`planning-related.py scan` so related-work is not rescanned. Standalone `/sw-tasks` omits those flags.

<!-- currency: refreshed 2026-08-30T01:56:00Z for terminal prepare (PRD 341) -->
