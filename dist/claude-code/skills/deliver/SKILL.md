---
name: deliver
description: Dependency-ordered deliver waves with dependent-branch stacking and integration branch lifecycle. Use when shipping frozen task-list phases or multi-feature integration waves. Does not merge to main or bypass the merge gate.
---
# Deliver orchestration

Layer above `/sw-ship` for **phase-mode** (frozen task-list phases stacking onto `<type>/<slug>`) and
**multi-feature mode** (independent features promoting via `integration/<stamp>`). Reuses `scripts/worktree.py`
and `skills/parallelism/` wholesale.

**Conductor:** load `skills/conductor/SKILL.md` for the shared autonomous loop (self-continuation,
legitimate halts, parallel dispatch, resumption). `/sw-deliver` is the pilot consumer; enforce
`rules/sw-conductor.mdc`. Do not re-author loop logic in this skill (R1, R3).


**Model tier:** build — resolve via `python3 scripts/resolve-model-tier.py --skill deliver`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## Deliver plan representation

Path: `.cursor/sw-deliver-plan.json` (machine-readable; see `.sw/layout.md`).

```json
{
  "verdict": "pass",
  "mode": "phase",
  "source_task_list": "docs/prds/<n>-<slug>/tasks-<n>-<slug>.md",
  "prd_number": "004",
  "target": {"type": "feat", "slug": "<slug>", "branch": "feat/<slug>"},
  "items": [{"id": "1", "slug": "<phase-slug>", "title": "...", "branch": "feat/<slug>-phase-<phase-slug>"}],
  "edges": [{"from": "1", "to": "2"}],
  "waves": [["1"], ["2", "3"]],
  "contention": {"serialized": ["doc-numbering"], "notes": "..."},
  "notices": []
}
```

Multi-feature mode uses `"mode": "multi-feature"` with conforming type-prefixed branches (e.g. `feat/<id>`); `pf/<id>` is prohibited (R24).

- **waves:** ordered batches; no intra-wave dependencies.
- **contention:** shared-migration refusal + living INDEX/numbering counters force serialization;
  `injectedEdges` records contention-forced edges merged into `edges` / `waves`.

### v1 deferrals (PRD 013 R13–R16)

- **Cross-feature waves (R13):** `plan --task-list <frozen> --items a,b --combine [--edges b:1]` mixes
  phase-mode units with multi-feature items; waves honor the combined edge set (`mode: combined`).
- **File-set edge inference (R14):** when `## Phase Dependencies` is absent, overlapping `**File:**`
  paths infer edges before sequential fallback; an explicit dependency table always wins.
- **Live phase status (R15):** `/sw-status` `derive --json` embeds `livePhaseStatus` for in-flight runs;
  `wave_living_docs.py phase-status-live` renders per-phase status, attempt, and blocker mid-run.
- **Contention → `/sw-tasks` (R16):** plan-time serialization notices persist to run-state
  `contentionFeedback`; surface suggestions (never auto-rewrite frozen tasks) via
  `scripts/wave_deliver.py <root> tasks-suggest [--target <type>/<slug>]`.
### Phase dependency fallback ladder (PRD 013 — authoritative)

`/sw-tasks` **requires** `## Phase Dependencies` at freeze. For **legacy** frozen lists that omit the table,
phase-mode planning applies this ladder in order (implemented in `wave_deliver.deps_to_edges` — no regression):

1. **Declared edges** — when `## Phase Dependencies` is present, rows are authoritative for wave planning.
2. **File-set inference** — when the table is absent, overlapping `**File:**` paths between phases infer
   serializing edges (`kind: file-set`) before any sequential fallback; notices include `file-set edge`.
3. **Sequential + notice** — when the table is absent and file-set inference finds no overlaps, strict
   sequential edges (`1→2`, `2→3`, …) apply with a `missing Phase Dependencies table` notice.

Explicit author edges always beat inference. Authors SHOULD declare parallelizable phases explicitly — do not
rely on deliver-time fallback for new multi-phase PRDs.


## Run-state artifacts

| Artifact | Path |
|----------|------|
| Plan | `.cursor/sw-deliver-plan.json` |
| Run state (scoped) | `.cursor/sw-deliver-state.<slug>.json` — canonical at **repo root** only (R28) |
| Orchestrator lock (scoped) | `.cursor/sw-deliver-<slug>.lock` |
| Concurrent-run index | `.cursor/sw-deliver-runs/index.json` |
| Living-doc serialization | `.cursor/sw-living-docs.lock` |
| Per-phase `/sw-ship` status | `.cursor/sw-deliver-runs/<phase-slug>/status.json` |
| Dispatch decisions | `.cursor/sw-deliver-runs/<phase-slug>/dispatch-decisions.json` |
| Phase step plan | `.cursor/sw-deliver-runs/<phase-slug>/phase-step-plan.json` |
| Execute step plan | `.cursor/sw-deliver-runs/<phase-slug>/execute-step-plan.json` |
| Integrate journal | `.cursor/sw-deliver-runs/<phase-slug>/integrate-journal.json` |
| Append-only progress log | `.cursor/sw-deliver-runs/run.log` |
| Legacy (migration only) | `.cursor/sw-deliver-state.json`, `.cursor/sw-deliver.lock` |


**Three-tier plan persistence (PRD 053):** wave batching → phase step plan → execute step plan. Phase entry
validates execute plan before fan-out when `execute.enabled` (default true) and the phase has ≥2 executable
sub-tasks; single-sub-task phases skip to monolithic `/sw-execute`. Sub-branches use
`feat/<slug>-phase-<phase-slug>--task-<ref>` and do not count toward `worktree.parallelCeiling`. Integrate
via `python3 scripts/wave.py execute integrate` is phase-executor scoped — never the conductor merge queue.

**PRD 004 supersede (D-053-7):** sub-task parallelism lives at the execute tier under `/sw-ship` when
`execute.enabled`; wave-tier batching is unchanged.

**Two-tier plan persistence (PRD 022):** validated wave-batching plans live on shared run-state
(`waveBatchingPlan`, conductor-only); validated phase step plans live under the phase run dir
(`phase-step-plan.json`, executor-owned). `orchestration.planPolicy` defaults to `canonical`; recorded mode
is honored on resume. Proposals validate via `python3 scripts/wave.py plan validate` before persist — see
`skills/conductor/SKILL.md` **Two-tier plan lifecycle**.

**Proposed-path (PRD 023):** live `proposed` on `/sw-deliver` requires the TR0 dependency gate
(`scripts/pilot_dependency_gate.py` / `scripts/test/pilot_022_prerequisite_check.py`) plus pilot opt-in guards
(see `core/commands/sw-deliver.md` **Pilot opt-in**). When enabled, `wave_deliver_loop.py` invokes wave/phase
`plan validate` with `--record-rejection` at each proposal site; rejections fall back to canonical waves/chain
without kernel changes. Default `canonical` is byte-identical to pre-023 behavior.

**Benefit metric + reporting (R31):** per-phase and run-level `benefitMetric` objects (numeric/enumerated only)
are captured at terminal phase status and rolled up on shared run-state. Operator soak comparisons use
`python3 scripts/wave.py plan benefit-report --pairs <path>` → `scripts/wave_plan_benefit.py`. Schema and
decision rule: `.sw/layout.md` **Deliver pilot run records**.

**Intra-phase fan-out snapshot:** `intraPhaseFanOut` on phase status / `phases.<id>` records the latest
validated partition, active worker count, and cap state; append-only audit lives in per-phase
`dispatch-decisions.json` (see `skills/parallelism/SKILL.md`).

Living artifacts under `.cursor/` are **never committed** (`/sw-commit` excludes them).


### Run-state detail

Provision-time materialization, unit-id derivation, run-state schema, locks, and progress logging: `references/run-state-artifacts.md`.

## Parallel scheduler (R14/R44)

See `references/parallel-merge-and-recovery.md` for schedule batches, conductor parallel dispatch, branch topology, stacking, integration/promotion, phase `/sw-ship` dispatch, conductor loop summary, sub-agent dispatch spike, and the serialized merge queue. The conductor in-turn loop runs `python3 scripts/wave.py deliver-loop` from the orchestrator worktree — see `skills/conductor/SKILL.md`.

## Terminal lifecycle

Terminal report, release bookkeeping, living-doc currency, incremental verify, terminal PR gate,
**base-branch preflight**, and post-run learnings (`scripts/wave.py memory learnings prepare` →
memory-preflight write): `references/terminal-lifecycle.md`.

## Issue-store integration

Annotation batches, safe close-on-merge, hierarchy projection, and inFlight tracking: `references/issue-store-integration.md`.



## Operator command index

Progressive-disclosure detail lives in `references/*.md`. This index preserves doc-currency grep
surfaces; expanded procedures are in the reference files linked above.

- **Scheduler:** `scripts/wave.py schedule` respects `parallelCeiling`; phase worktrees use
  `countsTowardCeiling`; dependents integrate via `forward-merge`.
- **Sub-agent dispatch spike (R63):** nested background dispatch is unreliable — default inline two-stage review per `rules/sw-subagent-dispatch.mdc`.
- **Merge queue:** `status collect` → `merge run-next` on `merge-ready-green`; `report terminal` when
  all phases merge; `bookkeeping record` / `bookkeeping revert` on the orchestrator worktree.
- **Failure routing:** `blast-radius apply` on blocked phases; `terminal deny` records rejected PRs.
- **Living INDEX:** lifecycle derives `not-started` | `complete` — never `in-progress` in INDEX tuples;
  run-state binds `source_task_list`.
- **Terminal PR:** `resume reconcile` then `terminal pr prepare` before the human merge gate.

- **Operator resume:** `/sw-deliver run <frozen-task-list>` (or `--issue N`); halt reports include `resumeCommand`.
- **Retrospective handoff:** `/sw-retrospective` / `/sw-retrospective --pre-merge` on the orchestrator
  worktree after phases merge (`compound.autonomy`); do not inline retro/compound/memory.
- **Living docs:** `living-docs reconcile --commit` after each green phase merge (INDEX / COMPLETION-LOG /
  GAP-BACKLOG on the feature branch).
- **Issue annotations (PRD 045):** `sw:deliver-annotate` comments before the human merge gate;
  `issue-batch-journal.json`; upsert-by-marker; linkage SoT is verify-only vs host introspection;
  emission points `deliver-annotation` / `deliver-annotation-ingest`; partial failure →
  `deliver-aborted-inconsistent`.
- **Push chokepoint:** workflow pushes use `scripts/git-push.py` → `secret-scan` before `git push`.


- **Operator worktree contract:** primary checkout is **operator shell only** — no implementation
  commits during deliver; `status.json` mirrors **phase → repo root** only.

- **Materialization:** private specs land under `.cursor/planning-materialized/` at provision
  (`lock-acquire` → `orchestrator-provision`); teardown clears orphans. Staged paths under the prefix are rejected by the **commit-boundary** barrier.
- **INDEX `inFlight` region (PRD 032):** deliver run-start writes a committed tuple after
  `lock-acquire` / before `orchestrator-provision`; cleared at run completion via
  `inflight-signal-clear`. Lifecycle `in-progress` is **not** stored in the tuple — PRD 033 derives
  it. Set `SW_INDEX_REGION_WRITER=deliver` on INDEX commits touching `inFlight`.

- **Task-list hierarchy** and inFlight tracking issues (PRD 046): see
  `references/issue-store-integration.md`.


## Concurrency invariants (PRD 036 — acceptance)

Operator-facing guarantees enforced by CI fixtures (`run_dual_ship_fixtures.py`,
`run_regression_remediation_fixtures.py`, `run_parallel_merge_safety_fixtures.py`,
`run_status_integrity_fixtures.py`):

1. **Single-flight ship (R1–R5):** one in-turn `/sw-ship --phase-mode` per phase head; per-head lease +
   PR idempotency; conductor never backgrounds ship on the same head.
2. **Regression remediation (R6–R8):** `verify:failed` routes to bounded `/sw-stabilize`; remediation
   attempts change the durable state signature; exhaustion halts with a consolidated report.
3. **Whole-batch merge (R9–R12):** no early single-phase merge while siblings lack validated terminal
   status; deterministic phase-id merge order; bounded auto-regen for deterministic-conflict paths only.
4. **Status provenance (R13–R17):** `ship-phase-status.py` emits an offline-regenerable provenance marker;
   forged or stale `merge-ready-green` is rejected; recovery reuses `/sw-ship --phase-mode --from <step>`
   — never hand-edit `status.json`.

Trust boundaries unchanged (R22): human merge to `main`, secret-scan push chokepoint, scoped deliver
locks, and frozen-doc CI gates.
