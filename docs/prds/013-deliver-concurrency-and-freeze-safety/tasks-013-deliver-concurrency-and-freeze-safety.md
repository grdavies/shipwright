---
date: 2026-06-25
topic: deliver-concurrency-and-freeze-safety
prd: docs/prds/013-deliver-concurrency-and-freeze-safety/013-prd-deliver-concurrency-and-freeze-safety.md
frozen: true
frozen_at: 2026-06-25
---

# Tasks — PRD 013 Deliver concurrency and freeze safety

Generated from the frozen PRD `013-prd-deliver-concurrency-and-freeze-safety.md` (effective union R1–R19).
Phases are dependency-ordered: freeze safety and the scoped-state resolver are foundational; the run index,
v1 deferrals, and docs/dist follow.

## Tasks

### 1. Freeze-time commit safety (M)

- [ ] 1.1 Commit frozen artifact onto `<type>/<slug>` at freeze via the shared helper (R1, R3, R5)
  - **File:** `core/commands/sw-freeze.md`, `scripts/wave_spec_seed.py`
  - **Expected:** after stamping, the shared spec-seed helper commits the frozen artifact onto the resolved `<type>/<slug>` (created from default branch if absent) using non-switching plumbing; never `main`; branch derived via the shared `/sw-deliver` resolver; same helper as `/sw-doc` afterTasks
- [ ] 1.2 Docs-only, brainstorm-excluded, idempotent commit (R2)
  - **File:** `scripts/wave_spec_seed.py`
  - **Expected:** commit excludes implementation files, `docs/brainstorms/**`, and untracked/ignored paths; a second freeze is a no-op
- [ ] 1.3 Verdict-independent (warn-not-block) wrapper (R4)
  - **File:** `core/commands/sw-freeze.md`, `scripts/check-frozen.sh`
  - **Expected:** a branch/commit failure logs a warning; the frontmatter stamp + INDEX entry still complete; artifact never left unstamped due to commit failure

### 2. Scoped deliver state + lock resolver (L)

- [ ] 2.1 Shared per-branch scoped path resolver (R6, R9)
  - **File:** `scripts/wave_state.py`
  - **Expected:** `scoped_paths(target)` → `.cursor/sw-deliver-state.<slug>.json` + `.cursor/sw-deliver-<slug>.lock`; slug derived from `--task-list`/target branch
- [ ] 2.2 Replace every hardcoded repo-wide path with the resolver (R9)
  - **File:** `scripts/wave_deliver.py`, `scripts/wave_deliver_loop.py`, `scripts/wave_merge.py`, `scripts/wave_lifecycle.py`, `scripts/wave_bookkeeping.py`, `scripts/wave_memory.py`, `scripts/wave_failure.py`, `scripts/wave_compound.py`, `scripts/wave_terminal.py`, `scripts/wave_living_docs.py`, `scripts/tasks-currency-gate.sh`, `scripts/docs-currency-gate.sh`, `scripts/ship-phase-status.sh`, `scripts/cleanup_lib.py`, `scripts/reconcile-status.sh`
  - **Expected:** no hardcoded `.cursor/sw-deliver-state.json` / `.cursor/sw-deliver.lock` remains; all resolve through 2.1
- [ ] 2.3 Scoped identity + lock liveness semantics (R7, R8)
  - **File:** `scripts/wave_deliver_loop.py`, `scripts/wave_state.py`
  - **Expected:** `assert_run_identity` keys on the scoped state file (branch A not rejected by branch B); scoped lock retains PRD 007 R44 liveness/stale-reclaim and refuses a live same-scope run
- [ ] 2.4 Legacy repo-wide state migration (R11)
  - **File:** `scripts/wave_state.py`
  - **Expected:** on first scoped read, an existing repo-wide `.cursor/sw-deliver-state.json` is adopted to its scoped path keyed by `source_task_list`; in-flight legacy run resumes

### 3. Concurrent-run index + enumeration + serialization (M)

- [ ] 3.1 Concurrent-run index (R10)
  - **File:** `scripts/wave_state.py`, `core/commands/sw-status.md`
  - **Expected:** `.cursor/sw-deliver-runs/index.json` (or `state.*.json` enumeration) lists each live scoped run (slug, task list, verdict, lock holder); `/sw-status` lists all runs
- [ ] 3.2 `/sw-cleanup` protects every scoped in-flight run (R10)
  - **File:** `scripts/cleanup_lib.py`
  - **Expected:** in-flight protection covers every scoped run holding a lock or open journal — not just one
- [ ] 3.3 Living-doc serialization preserved across parallel runs (R12)
  - **File:** `scripts/wave_living_docs.py`, `scripts/wave_bookkeeping.py`
  - **Expected:** existing contention/serialization model stays in force; two parallel scoped runs cannot corrupt `INDEX.md`/`CHANGELOG.md`

### 4. `/sw-deliver` v1 deferrals (L)

- [ ] 4.1 Cross-feature wave planning (R13)
  - **File:** `scripts/wave_deliver.py`
  - **Expected:** one plan mixes phase-mode + multi-feature units; waves computed over the combined edge set
- [ ] 4.2 File-set edge inference fallback (R14)
  - **File:** `scripts/wave_deliver.py`
  - **Expected:** absent `## Phase Dependencies` → edges inferred from overlapping `**File:**` declarations (fallback above sequential); explicit table always wins
- [ ] 4.3 Live per-phase status view (R15)
  - **File:** `scripts/wave_living_docs.py`, `core/commands/sw-status.md`
  - **Expected:** `run.log` + terminal report extended with a live per-phase view (status, attempt, blocker) rendered by `/sw-status` mid-run
- [ ] 4.4 Durable contention feedback into `/sw-tasks` re-run (R16)
  - **File:** `scripts/wave_deliver.py`, `core/skills/deliver/SKILL.md`
  - **Expected:** serialization notices persisted durably and surfaced as a `/sw-tasks` re-run suggestion (suggested explicit edge); no automatic task rewrite

### 5. Fixtures, docs, dist propagation (M)

- [ ] 5.1 Fixture suite for all new behaviors (R18)
  - **File:** `scripts/test/run-deliver-concurrency-fixtures.sh`, `.cursor/workflow.config.json`
  - **Expected:** every fixture named in the PRD Testing Strategy table exists and passes; suite registered in `verify.test`
- [ ] 5.2 Documentation updates (R19)
  - **File:** `core/skills/deliver/SKILL.md`, `core/skills/conductor/SKILL.md`, `rules/sw-workflow-sequencing.mdc`, `.sw/layout.md`, `docs/guides/workflows.md`
  - **Expected:** freeze-time commit, per-branch scoped state/lock paths, concurrent-run index, and the landed v1 deferrals documented; presence asserted by a fixture
- [ ] 5.3 Emitter propagation + freshness gate (R17)
  - **File:** `dist/cursor/**`, `dist/claude-code/**` via `python3 -m sw generate --all`
  - **Expected:** `dist/` regenerated; `scripts/test/run-emitter-fixtures.sh` passes

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | none |
| 3 | 2 |
| 4 | 2 |
| 5 | 1, 2, 3, 4 |

## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R1 | 1.1 | freeze-commit-on-feature-branch |
| R2 | 1.2 | freeze-commit-idempotent-docs-only |
| R3 | 1.1 | freeze-commit-on-feature-branch |
| R4 | 1.3 | freeze-commit-verdict-independent |
| R5 | 1.1 | freeze-seed-single-source |
| R6 | 2.1 | deliver-state-scoped-per-branch |
| R7 | 2.3 | deliver-lock-no-cross-block |
| R8 | 2.3 | deliver-identity-scoped |
| R9 | 2.2 | deliver-no-repo-wide-path |
| R10 | 3.1 | deliver-run-index-enumerates |
| R11 | 2.4 | deliver-legacy-state-migration |
| R12 | 3.3 | deliver-living-doc-serialized |
| R13 | 4.1 | deliver-cross-feature-wave-plan |
| R14 | 4.2 | deliver-file-set-edge-inference |
| R15 | 4.3 | deliver-live-phase-status |
| R16 | 4.4 | deliver-contention-durable-feedback |
| R17 | 5.3 | deliver-concurrency-emitter-freshness |
| R18 | 5.1 | run-deliver-concurrency-fixtures.sh (full suite) |
| R19 | 5.2 | deliver-concurrency-docs-presence |
