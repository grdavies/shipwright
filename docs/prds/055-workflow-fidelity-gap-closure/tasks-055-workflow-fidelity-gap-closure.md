---
frozen: true
frozen_at: 2026-07-02
date: 2026-07-02
topic: workflow-fidelity-gap-closure
prd: docs/prds/055-workflow-fidelity-gap-closure/055-prd-workflow-fidelity-gap-closure.md
visibility: public
---

# Tasks — PRD 055 Workflow fidelity & standing gap closure

Single-pass task list from the frozen PRD 055 spec union (R1–R27). Five phases mirror the rollout plan:
Thread A mechanical primitives → Thread B INDEX commit safety → Thread C deliver phase acceptance →
Thread D execute-tier authoring → Thread E gap capture unification. R26 satisfied at PRD freeze (verification
in phase 1).

## Relevant Files

- `core/sw-reference/build-chain-sot.json`, `scripts/copy-to-core.py`, `sw/emitter_base.py` — gap-022 (R1)
- `scripts/reconcile.py`, `core/commands/sw-memory-sync.md` — gap-024 (R3, R4)
- `scripts/planning_index_gen.py` — gap-020 (R5)
- `scripts/wave_living_docs.py`, `scripts/reconcile_lib.py`, `scripts/inflight_signal.py` — gap-002/007/008 (R6–R10)
- `scripts/wave_deliver_loop.py`, `scripts/phase_acceptance_gate.py`, `scripts/tasks-currency-gate.py` — gap-025 (R11–R15, R25)
- `scripts/gap-check-gate.py`, `scripts/ship-phase-status.py`, `core/sw-reference/kernel-classification.json` — R13
- `scripts/wave_state.py`, `scripts/execute_plan.py` — R12, R14
- `scripts/phase_sizing.py`, `core/skills/tasks/SKILL.md`, `core/commands/sw-tasks.md` — gap-023 (R16–R20)
- `scripts/planning_gap_capture.py`, `scripts/gap_backlog.py`, `scripts/planning_store.py` — gap-003 (R21–R27)
- `scripts/test/parity_compare.py`, `scripts/test/_runner.py`, `scripts/test_scope.py`, `scripts/wave_failure.py` — gap-026/027 (R28–R32)
- `scripts/test/run_emitter_fixtures.py`, `run_memory_sot_fixtures.py`, `run-deliver-fixtures.sh`, `run_planning_035_gap_lifecycle_fixtures.py`

## Tasks

### 1. Mechanical primitives — build-chain, supersede reconcile, INDEX newline (medium)

Thread A (gap-022, gap-024, gap-020). Low blast radius; unblocks honest dist/verify.

- [x] 1.0 Verify amendment supersede notes at PRD freeze (R26)
  - **File:** `docs/prds/046-issue-store-planning-graph/amendments/A2-*.md`, `A3-*.md`, `A4-*.md`, `docs/prds/045-issue-native-dev-tracking/amendments/A1-*.md`
  - **Expected:** each carries `superseded-by: PRD 055` in frontmatter; parents unchanged
  - **R-IDs:** R26
- [x] 1.1 Extend build-chain SoT excludes for developer test trees (R1)
  - **File:** `core/sw-reference/build-chain-sot.json`
  - **Expected:** `coreScripts.excludes` lists `unit_tests/` and `tests/`; manifest is sole source for copy/emitter
  - **R-IDs:** R1
- [x] 1.2 Align copy-to-core and emitter with SoT excludes (R1)
  - **File:** `scripts/copy-to-core.py`, `sw/emitter_base.py`
  - **Expected:** neither copies `unit_tests/`, `tests/`, or `test/` into `core/scripts/` or `dist/*/scripts/`
  - **R-IDs:** R1
- [x] 1.3 Regenerate dist and document repo-only harness (TR1)
  - **File:** `scripts/build-chain-sync.py`, `docs/guides/testing.md`
  - **Expected:** `build-chain-sync.py` green; `dist/{cursor,claude-code}/scripts/` has no developer test trees; testing guide states harness is repo-only
  - **R-IDs:** R1, R2
- [x] 1.4 Add emitter-excludes-developer-test-trees fixture (R2)
  - **File:** `scripts/test/run_emitter_fixtures.py`
  - **Expected:** fixture fails closed if `unit_tests/`, `tests/`, or `test/` appear under `dist/*/scripts/`
  - **R-IDs:** R2
- [x] 1.5 Port supersede subcommands to reconcile.py (R3, TR2)
  - **File:** `scripts/reconcile.py`
  - **Expected:** `append-superseded` and `supersede-reconcile` subcommands per PRD 015 contract; exit 0 on valid input
  - **R-IDs:** R3
- [x] 1.6 Refresh supersede docs and script-port-ledger (R4)
  - **File:** `core/commands/sw-memory-sync.md`, `core/sw-reference/script-port-ledger.json`, optional `scripts/reconcile-status.py` shim
  - **Expected:** supersede ops point at `reconcile.py`; memory-sync step 8 needs no agent deferral; one-release shim delegates if present
  - **R-IDs:** R4
- [x] 1.7 Add memory-sot-supersede-reconcile fixture (R4)
  - **File:** `scripts/test/run_memory_sot_fixtures.py`
  - **Expected:** `supersede-reconcile` exits 0 through redaction chokepoint
  - **R-IDs:** R4
- [x] 1.8 Fix planning_index_gen.replace_region_inner newline contract (R5, TR3)
  - **File:** `scripts/planning_index_gen.py`, `scripts/index-region-guard.py` (if present)
  - **Expected:** structural markers remain on their own line after regenerate; matches `render_region` contract
  - **R-IDs:** R5
- [x] 1.9 Add planning-index-marker-newline fixture (R5)
  - **File:** `scripts/test/run_planning_index_fixtures.py` or extension thereof
  - **Expected:** regenerate does not glue structural markers to table headers
  - **R-IDs:** R5

### 2. INDEX commit safety and terminal currency (medium)

Thread B (gap-002, gap-007, gap-008). Hard prerequisite for PRD 046.

- [ ] 2.1 Add shared default_branch_commit_guard primitive (R6, TR4, SC1)
  - **File:** `scripts/default_branch_commit_guard.py` (new) or `scripts/worktree_lib.py` extension
  - **Expected:** single Python-first helper refuses commits when resolved branch is `defaultBaseBranch`; fail closed
  - **R-IDs:** R6, R9
- [ ] 2.2 Wire guard into wave_living_docs commit paths (R6)
  - **File:** `scripts/wave_living_docs.py`
  - **Expected:** `cmd_reconcile`, `cmd_append_terminal`, `git_commit_living_docs` call guard before commit
  - **R-IDs:** R6
- [ ] 2.3 Wire guard into reconcile_lib.set_index_status (R6)
  - **File:** `scripts/reconcile_lib.py`
  - **Expected:** `set_index_status` refuses default-branch commits matching `reconcile_prd_index` guard
  - **R-IDs:** R6
- [ ] 2.4 Add living-docs-reconcile-refuses-default-branch fixture (R7)
  - **File:** `scripts/test/run_living_doc_fixtures.py` or deliver fixtures
  - **Expected:** `living-docs reconcile --commit` on `defaultBaseBranch` fails closed, never commits
  - **R-IDs:** R7
- [ ] 2.5 Wire terminal living-docs reconcile in finalize-completion (R8, TR5)
  - **File:** `scripts/wave_deliver_loop.py`
  - **Expected:** after `finalize-if-merged`, before `inflight_signal run-complete`, invoke `living-docs reconcile --commit` with orchestrator worktree; INDEX flips `complete` when merge detected
  - **R-IDs:** R8
- [ ] 2.6 Wire guard into inflight_signal.git_commit_inflight (R9)
  - **File:** `scripts/inflight_signal.py`
  - **Expected:** same `defaultBaseBranch` refusal as R6; `finalize-completion` call site explicitly guarded
  - **R-IDs:** R9
- [ ] 2.7 Add terminal INDEX currency fixtures (R10)
  - **File:** `scripts/test/run-deliver-fixtures.sh`
  - **Expected:** `finalize-completion-index-complete` and `inflight-run-complete-refuses-default-branch` pass
  - **R-IDs:** R10

### 3. Deliver phase acceptance gates (large)

Thread C (gap-025). Prevents merge-on-partial repeat of PRD 054 dogfood.

- [ ] 3.1 Implement phase_acceptance_gate (R11, TR6)
  - **File:** `scripts/phase_acceptance_gate.py` (new or extend `tasks-currency-gate.py`)
  - **Expected:** before merge-enqueue, verifies phase sub-task refs are ledger `done` + checkbox toggled; `declared-partial` requires durable ledger record; silent all-open fails closed
  - **R-IDs:** R11
- [ ] 3.2 Wire acceptance gate into merge_ready_in_flight_phases (R11, R25)
  - **File:** `scripts/wave_deliver_loop.py`
  - **Expected:** `merge_ready_in_flight_phases` calls acceptance gate; invokes gap-check without `--fast` on deliver kernel path
  - **R-IDs:** R11, R25
- [ ] 3.3 Harden wave_state ledger check for all-unchecked case (R12)
  - **File:** `scripts/wave_state.py`, `scripts/tasks-currency-gate.py`
  - **Expected:** ledger check fails when merge-ready-green but phase refs unchecked with no ledger `done`
  - **R-IDs:** R12
- [ ] 3.4 Add tasks-currency-unchecked-completed-work fixture (R12)
  - **File:** `scripts/test/run_tasks_currency_fixtures.py`
  - **Expected:** negative case fails closed (PRD 007 R15 gap)
  - **R-IDs:** R12
- [ ] 3.5 Bind gap-check-gate to durable status.json (R13)
  - **File:** `scripts/gap-check-gate.py`, `core/sw-reference/kernel-classification.json`
  - **Expected:** emits `gap-check.status.json` with binding `pass|halt`; kernel registry lists deliver binding
  - **R-IDs:** R13
- [ ] 3.6 Refuse merge-ready-green on gap-check halt (R13)
  - **File:** `scripts/ship-phase-status.py`
  - **Expected:** will not emit/consume `merge-ready-green` when gap-check verdict is `halt`
  - **R-IDs:** R13
- [ ] 3.7 Add gap-check deliver fixtures (R13, R25)
  - **File:** `scripts/test/run-deliver-fixtures.sh`
  - **Expected:** `gap-check-gate-blocks-merge-ready` and `deliver-gap-check-no-fast-skip` pass
  - **R-IDs:** R13, R25
- [ ] 3.8 Auto ledger record + checkbox on execute ref green (R14)
  - **File:** `scripts/wave_deliver_loop.py`, `scripts/execute_plan.py` or ship terminal hook
  - **Expected:** execute ref terminal `green` writes `ledger record` and toggles matching checkbox in frozen task file
  - **R-IDs:** R14
- [ ] 3.9 Add deliver-phase-blocked-open-subtasks fixture (R15)
  - **File:** `scripts/test/run-deliver-fixtures.sh`
  - **Expected:** `merge-ready-green` with open sub-tasks (e.g. 3.2/3.3) does not enqueue merge
  - **R-IDs:** R15
- [ ] 3.10 Update deliver and gap-check operator docs (TR9)
  - **File:** `core/commands/sw-deliver.md`, `core/skills/gap-check/SKILL.md`
  - **Expected:** documents phase acceptance ordering, gap-check binding, `--fast` prohibited on deliver merge path
  - **R-IDs:** R11, R13, R25

### 4. Execute-tier task authoring granularity (medium)

Thread D (gap-023). Authoring contract for future PRDs.

- [ ] 4.1 Emit bounded intra-phase refs at generation time (R16, R17, TR7)
  - **File:** `scripts/tasks_generate.py` or tasks authoring pipeline, `scripts/phase_sizing.py`
  - **Expected:** `/sw-tasks` output decomposes list-shaped PRD prose into bounded file-set refs; `phase_sizing.py` splits are part of frozen artifact not advisory-only stdout
  - **R-IDs:** R16, R17
- [ ] 4.2 Update tasks skill and command for execute-tier granularity (R18, TR9)
  - **File:** `core/skills/tasks/SKILL.md`, `core/commands/sw-tasks.md`
  - **Expected:** execute-tier granularity documented alongside Phase Dependencies and Traceability
  - **R-IDs:** R18
- [ ] 4.3 Add sw-tasks-execute-granularity fixture (R19)
  - **File:** `scripts/test/run_tasks_authoring_fixtures.py` (new or existing harness)
  - **Expected:** PRD with "port N suites" yields ≥N bounded refs or documented serial edges when contention forbids parallelism
  - **R-IDs:** R19
- [ ] 4.4 Document execute_plan runtime expansion escape hatch (R20)
  - **File:** `core/skills/tasks/SKILL.md`, `scripts/execute_plan.py` module docstring
  - **Expected:** frozen coarse lists expand at runtime only; no frozen-task mutation
  - **R-IDs:** R20

### 5. Gap capture unification and legacy backlog migration (large)

Thread E (gap-003). Clean file-side source before PRD 044; GAP-BACKLOG persists until migration complete (DL-5).

- [ ] 5.1 Route gap capture through planning_store for all backends (R21)
  - **File:** `scripts/planning_gap_capture.py`
  - **Expected:** `planning_store.put()` for file-store and issue-store; no bypass path for trivial gaps
  - **R-IDs:** R21
- [ ] 5.2 Reconcile feedback and living-status gap protocols (R22, TR9)
  - **File:** `core/skills/feedback/SKILL.md`, `core/skills/living-status/SKILL.md`
  - **Expected:** new capture writes canonical `docs/prds/gap/<unit-id>/`; GAP-BACKLOG is projection not hand-append target
  - **R-IDs:** R22
- [ ] 5.3 Canonical-id flip_schedule and flip_resolve (R23, TR8)
  - **File:** `scripts/gap_backlog.py`
  - **Expected:** keys on `docs/prds/gap/<unit-id>/` `id:` / `absorbs:` slugs; legacy `GAP-NNN` disjoint namespace handled via alias map or explicit migration
  - **R-IDs:** R23
- [ ] 5.4 Add gap-flip-schedule-canonical-id fixture (R23)
  - **File:** `scripts/test/run_planning_035_gap_lifecycle_fixtures.py`
  - **Expected:** `flip --schedule` from PRD `absorbs:` flips canonical units without legacy `GAP-NNN` collision
  - **R-IDs:** R23
- [ ] 5.5 Migrate open/scheduled legacy GAP-BACKLOG rows (R24, R27)
  - **File:** `docs/prds/GAP-BACKLOG.md`, `docs/prds/gap/<unit-id>/`
  - **Expected:** each legacy open/scheduled row has canonical unit or resolved closure with evidence before retirement
  - **R-IDs:** R24, R27
- [ ] 5.6 Add gap-backlog-migration-complete fixture (R24, R27)
  - **File:** `scripts/test/run_planning_035_gap_lifecycle_fixtures.py`
  - **Expected:** fails closed while unresolved legacy rows remain; passes only when migration gate satisfied
  - **R-IDs:** R24, R27
- [ ] 5.7 Conditional generated GAP-BACKLOG projection cutover (R22, R27)
  - **File:** `scripts/planning_legacy_projection.py` or gap_backlog renderer
  - **Expected:** generated read-only projection replaces hand rows only after R27 gate; no delete while open/scheduled legacy rows remain
  - **R-IDs:** R22, R27
- [ ] 5.8 Add gap-capture-planning-store-routing fixture (R21)
  - **File:** `scripts/test/run_planning_035_gap_lifecycle_fixtures.py`
  - **Expected:** file backend trivial gap routes through `planning_store.put()`
  - **R-IDs:** R21
- [ ] 5.9 Resolve absorbed gap units on terminal merge (Success criteria)
  - **File:** `docs/prds/gap/gap-*`, `scripts/gap_backlog.py`
  - **Expected:** all nine absorbed units `status: resolved` / `schedule: — (PRD 055)` after terminal PR merge
  - **R-IDs:** R23, R24, R27


### 6. Verify performance — parity compare and post-merge watchdog (medium)

Thread F (gap-026, gap-027). PRD 054 dogfood; amendment A1.

- [x] 6.1 Port parity_compare.py to pure Python (R28, TR10)
  - **File:** `scripts/test/parity_compare.py`, `scripts/unit_tests/meta/harness_parity.py`
  - **Expected:** compare hot path uses stdlib `hashlib` + tree walk; no bash subprocess; harness calls module directly
  - **R-IDs:** R28
- [x] 6.2 Tier-gate full dist compare to full scope (R29)
  - **File:** `scripts/test_scope.py`, `scripts/test/_runner.py`
  - **Expected:** `phase`/`fast` skip 841-file `dist/cursor` golden compare unless PRD 054 TR2 widen list matches
  - **R-IDs:** R29
- [x] 6.3 Add parity-compare-correctness fixture (R30)
  - **File:** `scripts/unit_tests/meta/test_parity.py` or `scripts/test/run_parity_fixtures.py`
  - **Expected:** happy/missing/extra/hash-diff cases pass after Python port
  - **R-IDs:** R30
- [x] 6.4 Add verify watchdog and progress logging (R31, TR11)
  - **File:** `scripts/test/_runner.py`, `scripts/wave_failure.py`
  - **Expected:** per-suite elapsed logging; consolidated halt on budget exhaustion with last suite id + resumeCommand
  - **R-IDs:** R31
- [x] 6.5 Add verify.watchdog.maxMinutes config and scoped post-merge default (R32)
  - **File:** `.cursor/workflow.config.json`, `.sw/config.schema.json`, `docs/guides/testing.md`
  - **Expected:** post-merge verify uses scoped path when widen list absent; budget documented
  - **R-IDs:** R32
- [x] 6.6 Add verify-watchdog-exhaustion fixture (R31)
  - **File:** `scripts/test/run_test_scope_fixtures.py` or deliver fixtures
  - **Expected:** simulated slow verify triggers halt report with resume command
  - **R-IDs:** R31
- [x] 6.7 Resolve gap-026 and gap-027 on terminal merge
  - **File:** `docs/prds/gap/gap-026-*`, `docs/prds/gap/gap-027-*`
  - **Expected:** both units `status: resolved`, schedule `PRD 055`
  - **R-IDs:** R28, R31

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 2 |
| 4 | 3 |
| 5 | 4 |
| 6 | 1 |

## Traceability

| R-ID | Task ref | Named test scenario | ZOMBIES checklist |
|------|----------|---------------------|-------------------|
| R1 | 1.1, 1.2, 1.3 | `emitter-excludes-developer-test-trees` — no test trees under `dist/*/scripts/` after build-chain-sync | Z, O, M, B, I, E, S |
| R2 | 1.4 | `emitter-excludes-developer-test-trees` fixture fails closed on harness paths in dist | Z, O, B, E |
| R3 | 1.5 | `memory-sot-supersede-reconcile` — `supersede-reconcile` exits 0 | Z, O, I, E |
| R4 | 1.6, 1.7 | `memory-sot-supersede-reconcile` + memory-sync step 8 without deferral | O, I, E, S |
| R5 | 1.8, 1.9 | `planning-index-marker-newline` — structural marker on own line after regenerate | Z, O, B, E |
| R6 | 2.1, 2.2, 2.3 | `living-docs-reconcile-refuses-default-branch` — reconcile --commit on default branch fails closed | Z, O, I, E, S |
| R7 | 2.4 | `living-docs-reconcile-refuses-default-branch` fixture | Z, B, E |
| R8 | 2.5 | `finalize-completion-index-complete` — terminal reconcile flips INDEX complete | O, I, S |
| R9 | 2.6 | `inflight-run-complete-refuses-default-branch` — inflight commit refuses default branch | Z, I, E |
| R10 | 2.7 | `finalize-completion-index-complete` + inflight default-branch refusal fixtures | O, M, S |
| R11 | 3.1, 3.2 | `deliver-phase-blocked-open-subtasks` — open refs block merge-enqueue | Z, O, M, B, I, E, S |
| R12 | 3.3, 3.4 | `tasks-currency-unchecked-completed-work` — all-unchecked with merge-ready fails | Z, O, B, E |
| R13 | 3.5, 3.6, 3.7 | `gap-check-gate-blocks-merge-ready` — halt verdict blocks merge-ready-green | O, I, E, S |
| R14 | 3.8 | execute ref green auto-writes ledger + checkbox for bound ref | O, I, S |
| R15 | 3.9 | `deliver-phase-blocked-open-subtasks` — partial phase cannot merge | O, M, B, E |
| R16 | 4.1 | `sw-tasks-execute-granularity` — N suites yield ≥N bounded refs | O, M, B |
| R17 | 4.1 | phase_sizing splits embedded in frozen task artifact not advisory stdout | O, I |
| R18 | 4.2 | tasks skill documents execute-tier granularity requirement | I |
| R19 | 4.3 | `sw-tasks-execute-granularity` fixture pass | O, M, B, E |
| R20 | 4.4 | frozen coarse list unchanged; runtime expansion only in execute_plan | O, I, S |
| R21 | 5.1, 5.8 | `gap-capture-planning-store-routing` — file backend uses put() | Z, O, I, E |
| R22 | 5.2, 5.7 | generated GAP-BACKLOG projection; no hand-append after migration gate | O, I, S |
| R23 | 5.3, 5.4, 5.9 | `gap-flip-schedule-canonical-id` — absorbs flips canonical units | O, M, I, E |
| R24 | 5.5, 5.6 | `gap-backlog-migration-complete` — zero unresolved legacy rows at retirement | Z, O, M, E |
| R25 | 3.2, 3.7, 3.10 | `deliver-gap-check-no-fast-skip` — merge path rejects --fast | O, I, E |
| R26 | 1.0 | frozen 046 A2/A3/A4 and 045 A1 carry `superseded-by: PRD 055` | O, I |
| R27 | 5.5, 5.6, 5.7 | `gap-backlog-migration-complete` gate before projection retirement | Z, O, E, S |
| R28 | 6.1, 6.2 | `parity-compare-correctness` — Python compare, no bash hot path | Z, O, B, E |
| R29 | 6.2 | phase scope skips full dist compare unless widen | O, I, S |
| R30 | 6.3 | parity happy/missing/extra/hash-diff unchanged | Z, O, B, E |
| R31 | 6.4, 6.6 | `verify-watchdog-exhaustion` — halt on budget with resume | O, I, E, S |
| R32 | 6.5 | scoped post-merge verify when widen absent | O, I, S |


## Notes

- Ship on `feat/workflow-fidelity-gap-closure` via `/sw-deliver` phase-mode; terminal PR to `main`.
- Phase 2 is a hard prerequisite for PRD 046 INDEX work; do not start 044 until Phase 5 migration gate passes.
- R26 verified complete at PRD freeze (task 1.0); do not re-edit superseded amendment bodies.
- Regenerate dist (`build-chain-sync.py`) after any core command/skill edits.
