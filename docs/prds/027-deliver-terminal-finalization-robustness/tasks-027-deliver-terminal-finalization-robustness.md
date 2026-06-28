---
date: 2026-06-27
topic: deliver-terminal-finalization-robustness
prd: docs/prds/027-deliver-terminal-finalization-robustness/027-prd-deliver-terminal-finalization-robustness.md
frozen: true
frozen_at: 2026-06-27
---

# Tasks — PRD 027 Deliver terminal finalization robustness

Generated from the frozen PRD spec union (R1–R13 — owned). Phase 1 unifies terminal completeness behind one
shared predicate and reinforces the conductor terminal transition (removes the primary stall trigger). Phase 2
hardens the phase-status write/read path so a background ship's `status.json` is always discoverable. Phase 3
resolves the five contributing factors that co-occurred in the PRD 026 run. Phase 4 reconciles the canonical
deliver-state path against the shipped PRD 013 A2 R28 resolver and wires every behavior's failing-before /
passing-after fixture into the deliver suite + `verify.test`, then regenerates `dist/` and the golden manifest.

This task list **consumes** (does not re-own) the PRD 013 A2 R28 canonical resolver
(`wave_state.resolve_state_path`), eager-teardown semantics (PRD 017 R17), merge single-flight (conductor R21),
and the `main` human merge gate — all of which remain unchanged.

## Tasks

### 1. Completeness unification + conductor terminal clause — M

- [ ] 1.1 Home the shared completeness predicate in `wave_state.py` (R1, per D1/D6)
  - **File:** `scripts/wave_state.py`
  - **Expected:** a single `TERMINAL_PHASE_STATUSES` constant (and/or `phase_complete(status)` helper) covering `green-merged`, `teardown-pending`, `teardown-complete` is defined in exactly one module; it reuses the existing `teardown-complete` enumeration; no behavior change to the status vocabulary. This is the single source the driver/terminal/compound import.
  - **R-IDs:** R1
- [ ] 1.2 Consume the shared predicate in driver, terminal, and compound (R1, R2, per D1)
  - **File:** `scripts/wave_deliver_loop.py`, `scripts/wave_terminal.py`, `scripts/wave_compound.py`
  - **Expected:** `wave_terminal.all_phases_green` and `wave_compound.all_phases_green` evaluate completeness via the R1 predicate; `wave_deliver_loop.MERGED_PHASE_STATUSES` becomes a re-export of the shared constant (not an independent `frozenset`); none of the three redefines the set locally. A run whose phases are `teardown-complete` after eager teardown passes the terminal retrospective and compound gates instead of failing closed with "requires all phases green-merged".
  - **R-IDs:** R1, R2
- [ ] 1.3 Conductor terminal-transition clause (R3, per D3)
  - **File:** `core/skills/conductor/SKILL.md` (mirror into `dist/` via the emitter)
  - **Expected:** under the existing no-status-pause / silent-dispatch-window sections, name the `retrospective` and `terminal-ship` transitions as `awaitAgent`-non-optional and restate the no-status-pause prohibition at the terminal boundary: while `verdict: running`, the agent performs the terminal step and re-invokes the driver in the same turn and must not emit a wave-complete status update combined with a scope or resume prompt. Reinforces R14/R16 at the terminal transition; no new top-level requirement number.
  - **R-IDs:** R3

### 2. Phase status write/read path hardening — M

- [ ] 2.1 Mirror-on-write the repo-root-canonical phase status (R4, per D2)
  - **File:** `scripts/ship-phase-status.sh` (and the phase dispatch env that sets `SW_RUN_DIR`)
  - **Expected:** the phase ship status writer writes `<integration-root>/.cursor/sw-deliver-runs/<phase-slug>/status.json` (mirrored on write) whenever the integration root is resolvable from `SW_REPO_ROOT` or deliver state, in addition to the worktree-local copy. No removal of the worktree-local write.
  - **R-IDs:** R4
- [ ] 2.2 Glob fallback in `wave_merge.status_file_for` (R5, per D2)
  - **File:** `scripts/wave_merge.py`
  - **Expected:** when the `phaseWorktrees[<id>].path` state lookup misses, `status_file_for` falls back to globbing `.sw-worktrees/*/.cursor/sw-deliver-runs/<phase-slug>/status.json` so a background phase ship's terminal status remains discoverable under state skew.
  - **R-IDs:** R5
- [ ] 2.3 `await-in-flight` advances on published status via both locations (R6)
  - **File:** `scripts/wave_deliver_loop.py`
  - **Expected:** for `backgroundDispatchedAt` phases, `await-in-flight` re-resolves status via both the canonical and worktree-local locations before sleeping; a phase that has published a terminal `status.json` in either location advances out of `await-in-flight` on the next driver tick with no manual copy or state patch.
  - **R-IDs:** R6

### 3. Contributing-factor resolution — M

- [ ] 3.1 Resolve `source_task_list` currency via orchestrator / integration branch (R7)
  - **File:** `scripts/wave_terminal.py`, `scripts/wave_deliver_loop.py`
  - **Expected:** the deliver terminal currency check resolves the frozen `source_task_list` via the orchestrator worktree / integration-branch path (not only the repo-root checkout) so `tasks_currency_ok` does not false-fail when the task list exists only on the integration worktree.
  - **R-IDs:** R7
- [ ] 3.2 Deterministic dependency-ordered parallel-wave merges (R8, per D7)
  - **File:** `scripts/wave_merge.py`
  - **Expected:** in merge-queue processing, ready phases are ordered by dependency topology and dependencies are forward-merged before dependents; a benign forward-merge conflict arising purely from out-of-order arrival resolves cleanly and is **not** a halt. A bounded rebase-retry is permitted only if forward-merge ordering is insufficient for the observed conflict class; a genuine content conflict surfaces as the legitimate ambiguous-merge halt.
  - **R-IDs:** R8
- [ ] 3.3 Classify post-merge verify failures; route environmental causes to bounded remediation (R9)
  - **File:** `scripts/wave_deliver_loop.py`
  - **Expected:** post-merge incremental `verify:failed` causes are classified; environmental causes (worktree `parallelCeiling`, fixture-harness unavailability) route to bounded remediation with the merge retained and are retried or cleared rather than latching a terminal block; the `blockers.json` cause enum distinguishes environmental from regression.
  - **R-IDs:** R9
- [ ] 3.4 Single consolidated supervised terminal checkpoint (R10)
  - **File:** `scripts/wave_terminal.py`, `scripts/wave_deliver_loop.py`
  - **Expected:** under `deliver.terminal.autonomy: supervised`, the terminal retrospective and ship checkpoint emits exactly one consolidated `report terminal` halt (the configured-checkpoint legitimate halt) and is never conflated with the mechanical completeness stall (which Phase 1 removes); under `auto` the conductor proceeds in-turn to the human merge gate.
  - **R-IDs:** R10
- [ ] 3.5 Supersede / clear stale `blockers.json` on progress (R11)
  - **File:** `scripts/wave_deliver_loop.py`
  - **Expected:** when the run makes progress after a prior halt, `blockers.json` is superseded or cleared so a stale `conductor:no-progress` (or other prior cause) is not re-surfaced; `report blockers` rewrites from current durable state only rather than appending stale causes.
  - **R-IDs:** R11

### 4. Canonical-state reconciliation + fixtures + dist parity — M

- [ ] 4.1 Assert canonical-state `phaseWorktrees` + reconcile GAP-028 (R12, per D5)
  - **File:** `scripts/wave_compound.py`, `scripts/wave_deliver_loop.py`, `docs/prds/GAP-BACKLOG.md`
  - **Expected:** verify `wave_compound.record-premerge` and the driver read/write through `wave_state.resolve_state_path` (no second resolver introduced); assert `phaseWorktrees` is present on the canonical repo-root state path the driver reads during in-flight phases; reconcile the stale GAP-028 backlog row from `planned` to resolved.
  - **R-IDs:** R12
- [ ] 4.2 Wire all R13 behavior fixtures into the deliver suite + `verify.test` (R13)
  - **File:** `scripts/test/run-deliver-fixtures.sh`, `scripts/test/run-deliver-loop-fixtures.sh`
  - **Expected:** each behavior has a failing-before / passing-after fixture wired into the deliver fixture suite and the `verify.test` manifest: `terminal-completeness-teardown-complete-passes`, `phase-status-canonical-mirror-discovered`, `phase-status-glob-fallback-discovered`, `await-in-flight-clears-on-status`, `tasks-currency-integration-worktree-ok`, `parallel-wave-out-of-order-merge-deterministic`, `post-merge-verify-environmental-remediates`, `supervised-terminal-checkpoint-single-halt`, `stale-blockers-superseded-on-progress`, `canonical-state-phaseworktrees-present`. Existing eager-teardown, merge single-flight, and scoped-state fixtures remain green (regression guard).
  - **R-IDs:** R13
- [ ] 4.3 Regenerate `dist/` + golden parity manifest (R13, per TR2/TR10)
  - **File:** `dist/cursor/**`, `dist/claude-code/**`
  - **Expected:** after any `core/` change (the conductor clause in 1.3), regenerate both `dist/` trees via the emitter and refresh the golden parity manifest; emitter freshness gate green; `dist/` parity with `core/`.
  - **R-IDs:** R13

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 2 |
| 4 | 3 |

## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R1 | 1.1, 1.2 | `terminal-completeness-teardown-complete-passes` |
| R2 | 1.2 | `terminal-completeness-teardown-complete-passes` |
| R3 | 1.3 | `supervised-terminal-checkpoint-single-halt` (terminal-transition no-status-pause) |
| R4 | 2.1 | `phase-status-canonical-mirror-discovered` |
| R5 | 2.2 | `phase-status-glob-fallback-discovered` |
| R6 | 2.3 | `await-in-flight-clears-on-status`; `phase-status-canonical-mirror-discovered`; `phase-status-glob-fallback-discovered` |
| R7 | 3.1 | `tasks-currency-integration-worktree-ok` |
| R8 | 3.2 | `parallel-wave-out-of-order-merge-deterministic` |
| R9 | 3.3 | `post-merge-verify-environmental-remediates` |
| R10 | 3.4 | `supervised-terminal-checkpoint-single-halt` |
| R11 | 3.5 | `stale-blockers-superseded-on-progress` |
| R12 | 4.1 | `canonical-state-phaseworktrees-present` |
| R13 | 4.2, 4.3 | deliver-suite wiring green: all ten R13 fixtures wired into `verify.test` (failing-before / passing-after) |

## Relevant Files

- `scripts/wave_state.py` — home of the shared `TERMINAL_PHASE_STATUSES` / `phase_complete` predicate (D6) and the PRD 013 A2 R28 canonical `resolve_state_path` resolver (consumed, not re-owned).
- `scripts/wave_deliver_loop.py` — deliver driver; `MERGED_PHASE_STATUSES` re-export, `await-in-flight` advancement, post-merge verify classification, stale-blocker supersession, currency resolution.
- `scripts/wave_terminal.py` — `all_phases_green` via shared predicate; currency resolution; single supervised terminal checkpoint.
- `scripts/wave_compound.py` — `all_phases_green` via shared predicate; `record-premerge` canonical-state verification.
- `scripts/ship-phase-status.sh` — mirror-on-write of the repo-root-canonical phase `status.json`.
- `scripts/wave_merge.py` — `status_file_for` glob fallback; dependency-ordered deterministic merge.
- `core/skills/conductor/SKILL.md` — terminal-transition no-status-pause clause (mirrored to `dist/`).
- `scripts/test/run-deliver-fixtures.sh`, `scripts/test/run-deliver-loop-fixtures.sh` — R13 fixture wiring.
- `docs/prds/GAP-BACKLOG.md` — GAP-028 reconcile to resolved (D5); absorbs GAP-041 / GAP-042.
- `dist/cursor/**`, `dist/claude-code/**` — regenerated emitter output + golden parity manifest.

## Notes

- **Decision alignment.** The phases trace the PRD Decision Log: D1/D6 (single shared predicate homed in
  `wave_state.py`) → Phase 1; D2 (write-side canonical mirror + read-side `.sw-worktrees/*` glob fallback) →
  Phase 2; D3 (mechanical fix primary + thin conductor clause) → 1.3; D4 (the five contributing factors
  R7–R11 belong in this PRD) → Phase 3; D5 (reconcile rather than duplicate the canonical resolver; GAP-028 is
  a stale `planned` row) and D7 (deterministic forward-merge-of-dependencies for R8, bounded rebase-retry only
  if insufficient) → Phases 3–4.
- **Invariants preserved.** Eager-teardown semantics (PRD 017 R17), merge single-flight (conductor R21),
  per-branch scoped state (PRD 013 R28), and the `main` human merge gate are unchanged; the only observable
  behavior change is that previously-stalled terminal runs now finalize. No new config knob is introduced.
- **Consumes, does not re-implement.** The canonical deliver-state write path (`wave_state.resolve_state_path`,
  already used by `wave_compound.record-premerge`) is verified and reconciled (R12), not duplicated.
- **Security posture.** No new external surface or host verbs; `status.json`, `blockers.json`, and run-state
  remain free of transcripts and secrets; the secret-scan pre-push and `main` human gate are untouched.
- **Sequential edges are intentional.** Phases 2–4 each edit modules touched by an earlier phase
  (`wave_deliver_loop.py`, `wave_merge.py`, `core/` → `dist/`), so the linear `1 → 2 → 3 → 4` dependency chain
  reflects genuine file-level edit dependencies, not sequential fallback.
