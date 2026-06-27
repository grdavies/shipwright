---
brainstorm: docs/brainstorms/2026-06-27-deliver-terminal-finalization-robustness-requirements.md
date: 2026-06-27
topic: deliver-terminal-finalization-robustness
frozen: true
frozen_at: 2026-06-27
---
# PRD 027 — Deliver terminal finalization robustness

## Overview

The autonomous deliver loop can complete every phase of a multi-phase run yet fail to finalize. After eager
phase-worktree teardown (PRD 017 R17) leaves a phase in status `teardown-complete`, the deliver driver
(`wave_deliver_loop.all_phases_merged`) treats the run as ready and routes to `retrospective`, but the
terminal and compound gates (`wave_terminal.all_phases_green`, `wave_compound.all_phases_green`) require
every phase to be exactly `green-merged` and therefore fail closed (exit 20). The run stalls with no
legitimate human gate. A second, independent defect compounds this: a background phase ship writes its
terminal `status.json` inside its phase worktree, and `wave_merge.status_file_for` only finds that copy
when `phaseWorktrees[<id>].path` is present in the repo-root state it reads — when the lookup misses, the
phase never advances out of `await-in-flight`.

This PRD unifies terminal completeness behind a single shared predicate, hardens the phase status
write/read path, reinforces the conductor's no-status-pause discipline at the terminal transition, and
resolves the cluster of contributing factors observed in the same PRD 026 deliver run. It changes neither
the human merge gate nor eager-teardown/merge-single-flight invariants. It absorbs GAP-041 and GAP-042.

This effort consumes — and does not re-implement — the canonical deliver-state write path shipped by
PRD 013 A2 R28 (`wave_state.resolve_state_path`, already used by `wave_compound.record-premerge`); the
state-split concern in GAP-042 is reconciled against that resolver rather than duplicated.

## Goals

- Make the deliver driver, terminal, and compound surfaces agree on what "all phases done" means, so a run
  whose phases are `teardown-complete` finalizes to the human merge gate without manual intervention.
- Guarantee a background phase ship's terminal `status.json` is always discoverable by the driver,
  independent of which worktree wrote it.
- Eliminate the terminal status-pause escape vector mechanically (by removing its trigger) and by an
  explicit conductor clause naming the terminal transition.
- Resolve the contributing factors that co-occurred in the PRD 026 run so none of them latches a
  non-legitimate halt.

## Non-Goals

- Re-implementing the canonical deliver-state write path — that is owned and shipped by PRD 013 A2 R28;
  this PRD verifies and reconciles only.
- Adding a proactive `status collect` inside `await-in-flight` as a third GAP-042 layer; the write-side
  canonical mirror plus read-side glob fallback are sufficient.
- Changing eager-teardown semantics (PRD 017 R17), merge single-flight (conductor R21), or per-branch
  scoped state (PRD 013 R28).
- Altering the final merge-to-`main` human gate; it remains human-gated and is never auto-merged.
- Doc-format parser robustness (GAP-045), backlog status automation (GAP-043/046/044), and the in-flight
  authoring guard (GAP-038) — these are separate efforts.

## Requirements

- **R1** A single shared completeness predicate (a `phase_complete(status)` helper or one
  `TERMINAL_PHASE_STATUSES` constant covering `green-merged`, `teardown-pending`, `teardown-complete`) is
  defined in exactly one module and imported by `wave_deliver_loop`, `wave_terminal`, and `wave_compound`;
  none of the three redefines the set locally.
- **R2** `wave_terminal.all_phases_green` and `wave_compound.all_phases_green` evaluate completeness via the
  R1 predicate, so a run whose phases are `teardown-complete` after eager teardown passes the terminal
  retrospective and compound gates instead of failing closed with "requires all phases green-merged".
- **R3** The conductor contract names the `retrospective` and `terminal-ship` transitions as
  `awaitAgent`-non-optional and restates the no-status-pause prohibition at the terminal boundary: while
  `verdict: running`, the agent performs the terminal step and re-invokes the driver in the same turn and
  must not emit a wave-complete status update combined with a scope or resume prompt.
- **R4** The phase ship status writer writes the repo-root-canonical status path
  `<integration-root>/.cursor/sw-deliver-runs/<phase-slug>/status.json` (mirrored on write) whenever the
  integration root is resolvable from `SW_REPO_ROOT` or deliver state, in addition to the worktree-local
  copy.
- **R5** `wave_merge.status_file_for` falls back to globbing
  `.sw-worktrees/*/.cursor/sw-deliver-runs/<phase-slug>/status.json` when the `phaseWorktrees[<id>].path`
  state lookup misses, so a background phase ship's terminal status remains discoverable under state skew.
- **R6** A background-dispatched phase that has published a terminal `status.json` in either the canonical
  or worktree-local location advances out of `await-in-flight` on the next driver tick with no manual copy
  or state patch.
- **R7** The deliver terminal currency check resolves the frozen `source_task_list` via the orchestrator or
  integration-branch path so `tasks_currency_ok` does not false-fail when the task list exists only on the
  integration worktree.
- **R8** Parallel-wave phase merges are enqueued and applied in dependency order; a benign forward-merge
  conflict arising purely from out-of-order arrival is resolved deterministically by forward-merging
  dependencies first, and only a genuine content conflict surfaces as the legitimate ambiguous-merge halt.
- **R9** Post-merge incremental verify failures on the integration branch attributable to environmental
  limits (worktree `parallelCeiling`, fixture-harness unavailability) route to bounded remediation and are
  retried or cleared rather than latching a terminal block; the merge is retained and the environmental
  cause is recorded distinctly from a real regression.
- **R10** Under `deliver.terminal.autonomy: supervised`, the terminal retrospective and ship checkpoint
  emits exactly one consolidated checkpoint (the configured-checkpoint legitimate halt) and is never
  conflated with the mechanical completeness stall; under `auto` the conductor proceeds in-turn to the
  human merge gate.
- **R11** When the run makes progress after a prior halt, `blockers.json` is superseded or cleared so a
  stale `conductor:no-progress` (or other prior cause) is not re-surfaced; `report blockers` reflects
  current durable state only.
- **R12** The canonical repo-root scoped deliver state carries `phaseWorktrees` for in-flight phases on the
  path the driver reads; this consumes the shipped PRD 013 A2 R28 canonical resolver
  (`wave_state.resolve_state_path`) and does not introduce a second resolver, and the stale GAP-028 backlog
  row is reconciled to resolved.
- **R13** Each behavior has a failing-before / passing-after fixture wired into the deliver fixture suite
  and `verify.test`: terminal completeness on `teardown-complete`; canonical-mirror discovery; glob-fallback
  discovery; `await-in-flight` clearing; currency on integration-only task list; deterministic out-of-order
  parallel-wave merge; single supervised terminal checkpoint; stale-`blockers.json` supersession.

## Technical Requirements

- **TR1** (R1, R2) Home the shared completeness predicate in `scripts/wave_state.py` (which already
  enumerates `teardown-complete`); `wave_deliver_loop`, `wave_terminal`, and `wave_compound` import it.
  `MERGED_PHASE_STATUSES` becomes a re-export of the shared constant, not an independent definition.
- **TR2** (R3) Add the terminal-transition clause to `core/skills/conductor/SKILL.md` under the existing
  no-status-pause / silent-dispatch-window sections; no new top-level requirement number — reinforce R14/R16
  at the `retrospective` / `terminal-ship` boundary. Mirror into `dist/` via the emitter.
- **TR3** (R4, R5, R6) Mirror-on-write in `scripts/ship-phase-status.sh` (and the phase dispatch env that
  sets `SW_RUN_DIR`); add the `.sw-worktrees/*` glob fallback to `wave_merge.status_file_for`; ensure
  `await-in-flight` for `backgroundDispatchedAt` phases re-resolves status via both locations before sleeping.
- **TR4** (R7) Resolve `source_task_list` for the terminal currency check via the orchestrator worktree /
  integration branch in `wave_terminal` / `wave_deliver_loop`, not only the repo-root checkout.
- **TR5** (R8) In `wave_merge` merge-queue processing, order ready phases by dependency topology and
  forward-merge dependencies before dependents; a conflict that resolves cleanly after dependency
  forward-merge is not a halt. A bounded rebase-retry is permitted only if forward-merge ordering is
  insufficient for the observed conflict class; genuine content conflicts remain the ambiguous-merge halt.
- **TR6** (R9) Classify post-merge `verify:failed` causes; environmental causes (ceiling, harness absence)
  route to bounded remediation with the merge retained; the cause enum distinguishes environmental from
  regression in `blockers.json`.
- **TR7** (R10) Ensure the supervised terminal checkpoint emits a single consolidated `report terminal`
  halt and that the mechanical completeness fix (TR1) prevents the stall from masquerading as a checkpoint.
- **TR8** (R11) On driver progress, supersede or clear stale `blockers.json`; `report blockers` rewrites
  from current durable state rather than appending stale causes.
- **TR9** (R12) Verify `wave_compound.record-premerge` and the driver read/write through
  `wave_state.resolve_state_path`; assert `phaseWorktrees` is present on the canonical path during in-flight
  phases; reconcile the GAP-028 backlog status.
- **TR10** (R13) Wire all R13 fixtures into `scripts/test/run-deliver-fixtures.sh` (and/or
  `run-deliver-loop-fixtures.sh`) and the `verify.test` manifest; regenerate `dist/` and the golden parity
  manifest after any `core/` change.

## Security & Compliance

- No new external surface or host verbs are introduced; the change is internal to deliver finalization and
  status resolution.
- `status.json`, `blockers.json`, and run-state remain free of transcripts and secrets; the benefit-metric
  numeric/enumerated contract (PRD 023 R31) is unchanged.
- Push and merge chokepoints (`scripts/git-push.sh`, single-flight merge) are preserved; no requirement
  weakens the secret-scan pre-push or the `main` human gate.

## Testing Strategy

Fixtures (failing-before / passing-after), wired into the deliver suite and `verify.test`:

| Fixture | Asserts | R-IDs |
| --- | --- | --- |
| `terminal-completeness-teardown-complete-passes` | `terminal retro run` + compound pass when all phases are `teardown-complete` | R1, R2 |
| `phase-status-canonical-mirror-discovered` | background ship status written to canonical path is read by the driver | R4, R6 |
| `phase-status-glob-fallback-discovered` | worktree-only status is discovered via `.sw-worktrees/*` glob when state lookup misses | R5, R6 |
| `await-in-flight-clears-on-status` | a `backgroundDispatchedAt` phase advances past `await-in-flight` on the next tick after status publish | R6 |
| `tasks-currency-integration-worktree-ok` | currency check passes when `source_task_list` exists only on the integration worktree | R7 |
| `parallel-wave-out-of-order-merge-deterministic` | out-of-order ready phases merge in dependency order without a spurious conflict halt | R8 |
| `post-merge-verify-environmental-remediates` | environmental post-merge verify failure routes to remediation, merge retained | R9 |
| `supervised-terminal-checkpoint-single-halt` | supervised mode emits one consolidated terminal checkpoint | R10 |
| `stale-blockers-superseded-on-progress` | a prior `conductor:no-progress` is not re-surfaced after progress | R11 |
| `canonical-state-phaseworktrees-present` | `phaseWorktrees` is present on the canonical repo-root state during in-flight phases | R12 |

Regression guard: existing eager-teardown, merge single-flight, and scoped-state fixtures must remain green.

## Rollout Plan

- **Phase 1 — Completeness unification (R1, R2, R3).** Lowest-risk, highest-leverage: single predicate +
  terminal/compound consumption + conductor clause. Removes the primary stall trigger.
- **Phase 2 — Phase status path (R4, R5, R6).** Write-side canonical mirror + read-side glob fallback +
  `await-in-flight` advancement.
- **Phase 3 — Contributing factors (R7–R11).** Currency resolution, parallel-wave merge ordering,
  environmental verify routing, supervised checkpoint, stale-blocker supersession.
- **Phase 4 — Reconciliation + fixtures (R12, R13).** Canonical-state assertion + GAP-028 reconcile; wire
  all fixtures; regenerate `dist/` + golden manifest.

Default behavior is unchanged except that previously-stalled terminal runs now finalize; no new config knob
is required and the change is backward compatible with existing runs and state files.

## Decision Log

- **D1** Single shared completeness predicate consumed by the driver, terminal, and compound surfaces —
  chosen over preserving `green-merged` + a separate `teardownAt` field, which would touch more modules
  (`wave_lifecycle`, `wave_state`, `wave_plan_benefit`) for the same outcome.
- **D2** Write-side repo-root-canonical mirror plus read-side `.sw-worktrees/*` glob fallback — chosen over
  the full four-layer GAP-042 fix; the remaining two layers are deferred and reconciled via D5.
- **D3** Mechanical fix primary with a thin conductor reinforcement clause — chosen over a heavy new
  conductor requirement, since R14/R16/R28 already exist and only the terminal transition needs naming.
- **D4** Include the five contributing factors (R7–R11) in this PRD rather than spawning separate gaps,
  because they co-occurred and compound the same terminal stall.
- **D5** Reconcile rather than duplicate the canonical deliver-state write path; PRD 013 A2 R28
  (`wave_state.resolve_state_path`) is verified live (`wave_compound.record-premerge` already uses it), so
  GAP-028 is a stale `planned` row to be reconciled to resolved.
- **D6** Home the shared predicate in `scripts/wave_state.py` (it already enumerates `teardown-complete`),
  avoiding a new module and keeping the status vocabulary single-sourced.
- **D7** For R8, deterministic forward-merge-of-dependencies is the primary strategy; a bounded rebase-retry
  is admitted only if forward-merge ordering proves insufficient for the observed parallel-wave conflict
  class, and genuine content conflicts remain the legitimate ambiguous-merge halt.

## Open Questions

None — all brainstorm open questions were resolved during drafting (predicate home: D6; parallel-wave merge
strategy: D7; GAP-028 status: verified shipped and reconciled per D5/R12).
