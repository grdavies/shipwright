---
date: 2026-06-25
topic: autonomous-orchestration-conductor
frozen: true
frozen_at: 2026-06-25
---

# PRD 009 — Autonomous orchestration conductor

## Overview

Shipwright's orchestrators stop and hand control back to the user at every agent boundary and run phases
strictly sequentially with no sub-agent dispatch. This defeats the plugin's core promise of being an
*automated* wrapper around its command surface: an orchestrator that pauses at every step and never
parallelizes is slower and more error-prone than running the atomic commands by hand.

This PRD introduces a single shared **conductor** contract — an agent-native autonomous loop that drives
plan → parallel phase dispatch → merge → terminal PR without re-prompting — while keeping the existing
deterministic `wave_*.py` scripts as the source of truth for state, merge, and gate decisions. The
conductor sits *above* the durable driver that PRD 007 (`deliver-autonomy-hardening`) landed: 007 made the
state core crash-safe and the driver resumable; 009 makes the **agent** stay in its turn and loop over that
driver, and adds conductor-level parallel sub-agent dispatch. `/sw-deliver` adopts the contract as the
pilot; `/sw-doc`, `/sw-ship`, `/sw-debug`, and `/sw-feedback` converge onto the same contract in follow-on
PRDs (enumerated here, not built).

It derives from the brainstorm
`docs/brainstorms/2026-06-25-autonomous-orchestration-conductor-requirements.md` (R1–R36) and the concrete
failures observed delivering PRD 008 (`model-tier-setup-defaults`): a human had to type "continue deliver"
between every phase, zero background sub-agents launched despite four free worktree slots, and a long tail
of driver defects that forced phases to be merged by hand.

## Goals

1. A frozen multi-phase task list delivered via `/sw-deliver run <path>` reaches the terminal-PR human gate
   with zero "continue deliver" style re-prompts under default configuration.
2. A wave with two or more dependency-ready phases runs them as concurrent background sub-agents in disjoint
   worktrees (up to `worktree.parallelCeiling`), not serially — demonstrated by an observable peak-concurrency
   metric (≥2 simultaneously active phase worktrees) in the pilot fixture, on task lists that actually expose
   parallelizable phases.
3. All phase merges occur through the serialized merge queue (`merge run-next`) on a clean run — zero manual
   hand-merges and zero hand-patched phase status (the measurable error-rate proxy for the "more error-prone
   by hand" premise) — with every safety invariant preserved under autonomy and parallelism.
4. A fresh agent with no prior chat context resumes an interrupted run from durable state alone and
   continues autonomously to the next legitimate halt.
5. The reliability defects observed in the PRD 008 run (R25–R31) are closed, each with a
   failing-before / passing-after regression fixture, so the conductor can rely on the primitives.
6. The conductor contract is a single referenced primitive; `/sw-deliver` consumes it without re-authoring
   loop logic, and the adoption path for the other orchestrators is documented.
7. An unattended `autonomous` run is bounded: per-phase liveness/remediation budgets and a run-level
   ceiling guarantee termination at a clean halt rather than a runaway loop, so default hands-off mode is
   safe to leave running.

## Non-Goals

- Conductor adoption *implementation* for `/sw-doc`, `/sw-ship`, `/sw-debug`, `/sw-feedback` — enumerated
  here, built in follow-on PRDs after the pilot proves the contract.
- Auto-merge to `main` — the terminal merge to `main` stays a human gate by default; full hands-off
  main-merge is explicitly out of scope.
- Nested sub-agent dispatch as a relied-upon capability — avoided by design (all dispatch at the
  conductor level), not built.
- Multi-feature mode / `integration/<stamp>` promotion changes beyond what the conductor contract requires.
- Changes to documentation-pipeline semantics (`/sw-brainstorm` → `/sw-prd` → `/sw-tasks`) other than
  orchestrator autonomy.
- Rebuilding the durable driver or crash-safe state core delivered by PRD 007 — 009 consumes those
  primitives and only hardens the residual defects enumerated in R25–R31.

## Requirements

R-IDs are carried forward verbatim from the frozen brainstorm (stable namespace; do not renumber). The
groups (A–G) and numeric R-ID order are preserved.

### A. Conductor contract (shared primitive)

- **R1** A reusable conductor contract is defined as a single skill/rule specifying self-continuation, the
  legitimate-halt set, parallel sub-agent dispatch, and durable-state resumption — referenced (not
  re-authored) by each orchestrator that adopts it.
- **R2** The conductor drives all *mechanical* and *agent* steps of a run without requiring any human
  message between steps, except at a legitimate halt (R10).
- **R3** The conductor invokes the existing `wave_*.py` primitives for every state transition, merge-queue
  operation, gate evaluation, and bookkeeping action; it never re-implements state logic in prose.
- **R4** A fresh agent with no prior chat context can resume an interrupted run from durable state
  (`.cursor/sw-deliver-state.json` + plan + run log) and continue autonomously to the next legitimate halt.
- **R5** The conductor contract is platform-neutral in `core/` and is emitted to both `dist/cursor/` and
  `dist/claude-code/` by the existing generator, with the freshness gate passing.

### B. Autonomous self-continuation

- **R6** When the driver returns an agent action (`dispatch-ship`, `remediate`, `terminal-ship`,
  `compound-ship`), the conductor performs the agent work and then immediately re-invokes the driver within
  the same turn — no "continue" prompt is required.
- **R7** The conductor does not end its turn while progress is possible and no legitimate halt condition is
  met.
- **R8** For time-gated external waits (terminal-PR CI), the conductor arms a background self-wake sentinel
  (`notify_on_output`) and resumes automatically when the watched event fires, rather than yielding to the
  user.
- **R9** Self-wake watchers and heartbeats are uniquely named per run, are torn down on terminal halt, and
  never leave orphaned background processes after the run completes or is stopped.

### C. Legitimate halts only

- **R10** The conductor halts for human input only on: (a) final merge to `main`; (b) a phase whose
  remediation budget (`deliver.remediation.maxAttempts`) is exhausted; (c) a genuine ambiguous merge
  conflict or a destructive/irreversible action; (d) a user-configured checkpoint (`doc.afterTasks: confirm`,
  `deliver.phaseAckCadence: K>0`).
- **R11** No halt occurs for routine per-phase progression, status collection, wave advancement, or release
  bookkeeping.
- **R12** Every halt emits a single consolidated, actionable report (what is blocked, why, and the exact
  resume command) — never a bare "continue?" prompt.
- **R13** Default out-of-box behavior requires no re-prompting: with no extra configuration a frozen task
  list delivers end-to-end to the terminal-PR human gate autonomously.

### D. Adaptive parallel dispatch

- **R14** The conductor dispatches all dependency-ready phases in the current wave concurrently as
  background sub-agents, bounded by `worktree.parallelCeiling`, each in its own isolated phase worktree.
- **R15** When a wave exceeds the ceiling, phases are dispatched in greedy sequential batches; a running
  phase is never unwound to admit a queued one (consistent with `wave.sh schedule`).
- **R16** Phase sub-agents are dispatched only from the conductor (orchestrator) level; the conductor never
  relies on nested dispatch (a sub-agent spawning sub-agents).
- **R17** Within a phase, parallel task/review sub-agents are used only when `rules/sw-subagent-dispatch.mdc`
  heuristics trip; otherwise the phase runs inline two-stage review. This decision is logged in the run
  record.
- **R18** Only wave-level phase worktrees count toward `parallelCeiling`; intra-phase sub-agent dispatch
  does not consume ceiling slots (preserves the existing ceiling accounting).
- **R19** The conductor collects phase outcomes exclusively from the durable
  `.cursor/sw-deliver-runs/<phase>/status.json` path — never from ephemeral sub-agent logs — preserving
  resumability for parallel runs.
- **R20** Parallel dispatch honors contention serialization (shared-migration paths, `INDEX.md`/numbering,
  `CHANGELOG.md`/`version.txt`): contended phases are never run concurrently.

### E. Safety invariants preserved under autonomy + parallelism

- **R21** Merges into `<type>/<slug>` remain single-flight through the serialized merge queue with journal +
  lock; concurrent phase completion never produces a double-merge.
- **R22** A phase merges only after its gate is green and the review barrier is satisfied; the conductor
  never auto-merges to `main`.
- **R23** All pushes route through `scripts/git-push.sh` (the secret-scan chokepoint); the conductor
  introduces no raw `git push`.
- **R24** A blocked phase blocks only its transitive dependents (blast radius); independent sibling phases
  continue and may still auto-merge when green.

### F. Reliability hardening (traceable to the PRD 008 run)

- **R25** `spec-seed` records `specSeed` in run-state even when the seed commit already exists (idempotent
  skip); the driver never loops on an already-satisfied `spec-seed` action.
- **R26** `merge run-next` post-merge verify failure routes to `/sw-stabilize` and marks the phase `blocked`
  without silently reverting a merge the conductor cannot then re-drive; revert behavior is explicit,
  logged, and reflected in state.
- **R27** `wave.sh` subcommand dispatchers — `status collect`, `merge run-next`/`enqueue`, and `report`
  — each accept their documented argument form without duplicate-argument breakage, so the conductor's
  autonomous collect/merge/report path is reachable through the shell entrypoint (not only by calling the
  Python modules directly).
- **R28** Driver error paths (e.g. provision failures) emit a structured `{verdict:"fail", …}` JSON and exit
  cleanly — no uncaught `TypeError` or stack traces.
- **R29** A status-vocabulary guard enforces the allowed set (`pending` | `in-flight` | `green-merged` |
  `blocked` | `rejected`) and rejects any out-of-vocabulary write; the merge primitive already sets
  `green-merged` correctly, so the guard removes the operator hand-patching that the missing enforcement
  previously invited.
- **R30** A new run refuses to start (or explicitly resets) when stale run-state from a different
  `source_task_list`/`prd_number` is present, instead of silently inheriting it.
- **R31** Orchestrator provision succeeds without requiring the operator to manually move the primary
  checkout off the target branch first (handles the detached-head case automatically).
- **R32** Each reliability defect (R25–R31) has a regression fixture wired into the test gate so the
  conductor can depend on the primitives.

### G. Per-orchestrator adoption audit + convergence

- **R33** The PRD captures a per-orchestrator audit of `/sw-doc`, `/sw-ship`, `/sw-debug`, and `/sw-feedback`
  identifying each point where the orchestrator yields the turn unnecessarily or fails to parallelize
  independent work.
- **R34** `/sw-deliver` adopts the conductor contract as the pilot and is validated against R6–R20
  end-to-end.
- **R35** Adoption requirements for the remaining orchestrators are enumerated (sequenced after the pilot),
  each referencing the shared contract rather than duplicating it.
- **R36** Command/skill descriptions are updated so the autonomy/parallelism behavior and the
  legitimate-halt set are documented at the surface a user reads (`/sw-deliver` first).

### H. Autonomy & parallelism hardening (doc-review panel)

*(Added after the 009 persona panel surfaced liveness, loop-termination, contention-detection, and
merge-serialization gaps that the in-turn autonomous loop and conductor-level parallelism introduce. New
stable R-IDs; do not renumber R1–R36.)*

- **R37** Each dispatched phase sub-agent has a liveness bound (per-phase timeout / heartbeat); on expiry
  without a terminal `status.json` the conductor marks the phase `blocked`, emits the consolidated report
  (R12), and treats it as a legitimate halt — a silently dead or hung background sub-agent never leaves the
  conductor spinning or blocked forever (closes ADV-1; extends R10).
- **R38** The conductor's in-turn loop has a documented maximum-iteration bound and a no-progress circuit
  breaker (identical `nextAction` + unchanged durable-state signature N times → escalate to a clean halt),
  registered in `rules/sw-subagent-dispatch.mdc` hard-stops, so a runaway loop cannot churn indefinitely
  (closes ADV-4).
- **R39** Contention detection (R20) has a mechanical basis: contended paths are derived deterministically
  from the plan (declared phase touch-paths or a single-sourced path set), and ambiguous/over-broad cases
  fail safe to sequential — contention is never decided by prose (closes ADV-5).
- **R40** When an external wait (terminal-PR CI self-wake) reaches `checks.watch.maxWaitMinutes` without a
  terminal signal, the conductor routes to a clean consolidated halt (R12) rather than spinning or trusting
  stale output; "external wait exhausted" is part of the legitimate-halt set, and a wake always re-derives
  the next action from durable state (closes ADV-3; extends R10).
- **R41** Merge-queue invocation is conductor-serialized — phase sub-agents never call `merge run-next`;
  the single conductor enqueues/runs merges — and the queue lock is acquired atomically, so simultaneous
  phase completion yields exactly one merge with no time-of-check/time-of-use double-merge (closes ADV-2;
  reinforces R21).
- **R42** A run-level autonomy budget (cumulative wall-clock / total-iteration ceiling) converts a runaway
  unattended `autonomous` run into a clean consolidated halt, complementing the per-phase remediation
  budget so the default-hands-off mode cannot churn without bound (closes ADV-6).
- **R43** The stale-state guard (R30) distinguishes a legitimate resume (R4) from a new run carrying stale
  state using a normalized/canonical identity (canonical task-list path or stored run-id), so resuming the
  same run never false-aborts; only a true identity mismatch aborts or requires explicit reset
  (closes ADV-7).
- **R44** Waiting on parallel-wave phase completion has a defined contract: the conductor either polls the
  durable `status.json` set within bounded budget or arms the same per-run self-wake sentinel keyed on
  status appearance, then resumes autonomously — the "wait for N parallel phases, then continue" mechanism
  is specified, not implicit (closes F4; complements R8/R19).
- **R45** When a phase runs as a backgrounded parallel sub-agent, intra-phase task/review dispatch degrades
  to inline two-stage review (no nesting); intra-phase sub-agent dispatch (R17) is permitted only when the
  conductor runs that phase inline, so the "no nested dispatch" invariant (R16) holds under parallelism
  (closes F3).
- **R46** Self-wake (R8) has an environment fallback: where the harness cannot deliver output-notification
  auto-resume (e.g. cloud/headless agents), the conductor degrades to a bounded in-turn poll up to
  `checks.watch.maxWaitMinutes` then a single consolidated halt (R12), so the zero-re-prompt promise has a
  defined behavior in every environment (closes F2).

## Technical Requirements

- **TR1 — Conductor contract artifact.** Add `core/skills/conductor/SKILL.md` defining the shared loop:
  self-continuation rule (R6/R7), the legitimate-halt set (R10–R12), the conductor-level parallel-dispatch
  protocol (R14–R20), and durable-state resumption (R4). It is referenced by orchestrators, never
  re-authored inline (R1, R3). A thin `core/rules/sw-conductor.mdc` encodes the always-on guardrail subset
  (no nested dispatch; halt only on the legitimate set) so enforcement does not rely on prose alone.
- **TR2 — In-turn self-continuation for `/sw-deliver`.** Update `core/commands/sw-deliver.md` and
  `core/skills/deliver/SKILL.md` so that after the driver emits `awaitAgent: true` for an agent action, the
  conductor performs the agent work and immediately re-invokes `bash scripts/wave.sh deliver-loop` within
  the same turn, looping until a legitimate halt — it never ends the turn while `nextAction` is runnable
  and no halt condition is met (R2, R6, R7, R13). This in-turn loop carries the documented max-iteration
  bound + no-progress circuit breaker of TR21 (R38). `/sw-deliver` is the pilot consumer validated against
  R6–R20 end-to-end (R34).
- **TR3 — Self-wake sentinel for time-gated waits.** For terminal-PR CI, the conductor arms a uniquely-named
  background shell with `notify_on_output` (reusing the `loop`/`babysit` sentinel pattern), keyed on the run
  id, and resumes when the watched event fires; on terminal halt every watcher/heartbeat for the run id is
  torn down (R8, R9). The watch cadence reuses `checks.watch.pollSeconds`/`checks.watch.maxWaitMinutes`
  (no new knob). On `maxWaitMinutes` expiry the conductor routes to a clean consolidated halt and a wake
  always re-derives next action from durable state (R40). Where the harness cannot auto-resume on output
  notification (cloud/headless agents), self-wake degrades to a bounded in-turn poll up to
  `maxWaitMinutes` then a single consolidated halt (R46). The same wait contract covers parallel-wave phase
  completion, not only CI (R44).
- **TR4 — Conductor-level parallel phase dispatch.** The conductor computes ready phases via
  `bash scripts/wave.sh schedule` (ceiling-bounded greedy batches) and dispatches each ready phase as a
  background `Task` sub-agent in its own phase worktree, all from the orchestrator level (R14–R16, R34). It
  collects outcomes solely from `.cursor/sw-deliver-runs/<phase>/status.json` (R19) and never unwinds a
  running phase to admit a queued one (R15). Contention serialization is enforced at **plan time** —
  `scripts/wave_deliver.py` injects contention edges (shared-migration paths, `INDEX.md`/numbering,
  `CHANGELOG.md`/`version.txt`) that push contended phases into different waves — so the conductor honors
  wave boundaries from the plan rather than re-checking inside a wave (R20, R39).
- **TR5 — Intra-phase dispatch gating.** Within a phase, task/review sub-agent dispatch fires only when
  `rules/sw-subagent-dispatch.mdc` heuristics trip (≈8+ files / independent task sets); otherwise inline
  two-stage review. The decision is recorded in the per-phase run record, and intra-phase dispatch does not
  consume `parallelCeiling` slots (R17, R18). When the phase itself runs as a backgrounded parallel
  sub-agent, intra-phase dispatch degrades to inline two-stage review so the "no nested dispatch" invariant
  (R16) holds; intra-phase dispatch is used only when the conductor runs that phase inline (R45).
- **TR6 — Safety invariants under parallelism.** The serialized merge queue (journal + lock) admits exactly
  one merge at a time even when phases finish concurrently (R21); merge-queue invocation is
  conductor-serialized (phase sub-agents never call `merge run-next`) and the queue lock is acquired
  atomically, closing the simultaneous-completion TOCTOU window (R41); `merge run-next` only merges a
  green-gated, review-satisfied phase and never targets `main` (R22); all pushes go through
  `scripts/git-push.sh` (R23); blast-radius blocking limits a blocked phase to its transitive dependents
  while green siblings continue (R24). These reuse the PRD 007 merge/lock/push primitives (009 re-states
  none of them) and add concurrency fixtures; the reuse is reachable only once the TR9 dispatch fix lands.
- **TR7 — `spec-seed` idempotent state record.** `scripts/wave.sh spec-seed` (and `scripts/wave_deliver.py`)
  set `specSeed` in run-state on the idempotent-skip path (seed commit already present), so
  `compute_next_action` never loops on a satisfied `spec-seed` action (R25).
- **TR8 — Merge post-verify routing.** `scripts/wave_merge.py` `merge run-next` routes a post-merge verify
  failure to `/sw-stabilize` and marks the phase `blocked`; on the default path it does **not** issue a
  `git revert` of the just-merged phase (the current `verify run-after-merge` → `revert phase` auto-revert
  is removed/made opt-in). State is left re-drivable; any revert is explicit, logged, and reflected in state
  (R26).
- **TR9 — `wave.sh` dispatcher argument hygiene.** Every `wave.sh` subcommand dispatcher that prefixes a
  literal domain token (`status`, `merge`, `report`) forwards `${@:2}` to its Python module (matching the
  correct `phase dispatch-env` / `state` branches) so the real subcommand is not consumed as the domain.
  Fixtures exercise `wave.sh status collect`, `wave.sh merge run-next`, and `wave.sh report terminal`
  end-to-end through the shell entrypoint — not just the Python modules directly (which is how the defect
  escaped the 007 gate) (R27).
- **TR10 — Structured driver error paths.** Fix the `fail(error, …, **data)` keyword-collision in
  `scripts/wave_deliver.py`/`wave_deliver_loop.py` (strip/rename the colliding `error` key before the
  `**data` splat) across all `execute_mechanical` error paths, so any sub-step failure (provision, lock,
  plan, merge) emits `{"verdict":"fail", …}` JSON and exits cleanly with no uncaught `TypeError`/stack
  trace (R28).
- **TR11 — Phase status-vocabulary guard.** Add an enforcing guard that rejects any status write outside
  `pending | in-flight | green-merged | blocked | rejected`. The merge primitive already sets `green-merged`
  correctly via `scripts/wave_merge.py`; the guard is the new work (the failing-before fixture targets the
  missing enforcement, not a mis-set in the merge path) (R29).
- **TR12 — Stale-state guard with resume discrimination.** At loop entry the driver compares the requested
  run identity against `.cursor/sw-deliver-state.json` using a normalized/canonical task-list path (or stored
  run-id), not a raw string: a matching identity is a legitimate resume (proceed, R4); a true mismatch aborts
  with a consolidated halt or clears under explicit `--reset`, instead of silently inheriting prior-PRD
  state (R30, R43).
- **TR13 — Detached-head-safe provision.** `scripts/wave_lifecycle.py` orchestrator provision auto-handles
  the primary-on-target-branch case **only when the primary tree is clean** (detach or check out
  `origin/HEAD` automatically); a **dirty** primary on the target branch still fails closed with remediation
  so autonomy never silently moves uncommitted work (R31).
- **TR14 — Reliability regression fixtures.** Each of R25–R31 gets a failing-before / passing-after fixture
  wired into the deliver/state test suites referenced by `workflow.config.json` `verify.test` (R32).
- **TR15 — Autonomy config knob.** Add `deliver.autonomy: supervised | autonomous` (default `autonomous`)
  to the config schema, example config, and `setup` seeding; `supervised` raises the halt set to include
  per-phase acknowledgement, `autonomous` uses the minimal legitimate-halt set (R10, R13; resolves OQ1).
- **TR19 — Phase liveness watchdog.** Each dispatched phase sub-agent carries a per-phase timeout/heartbeat
  (reusing `checks.watch.maxWaitMinutes` or a `deliver.phaseTimeoutMinutes` knob); on expiry without a
  terminal `status.json` the conductor marks the phase `blocked`, emits the consolidated report, and treats
  it as a legitimate halt — a dead/hung background sub-agent is detected, never spun on (R37).
- **TR20 — Run-level autonomy budget.** Add a run-level ceiling (cumulative wall-clock / total-iteration,
  e.g. `deliver.autonomy.maxRunMinutes`) to the config schema/example/setup; when exceeded, an `autonomous`
  run converts to a clean consolidated halt, complementing the per-phase `deliver.remediation.maxAttempts`
  budget (R42).
- **TR21 — Conductor loop hard-stop.** Register the conductor's in-turn loop in
  `rules/sw-subagent-dispatch.mdc` hard-stops with a documented max-iteration bound and a no-progress
  circuit breaker: identical `nextAction` plus an unchanged durable-state signature across N iterations
  escalates to a clean consolidated halt rather than churning (R38).
- **TR16 — Per-orchestrator audit + adoption enumeration.** Author the audit of `/sw-doc`, `/sw-ship`,
  `/sw-debug`, `/sw-feedback` (turn-yield + missed-parallelism points) and the enumerated, sequenced
  adoption requirements for each — referencing the shared contract, not duplicating it — as a committed
  artifact under `docs/prds/009-autonomous-orchestration-conductor/` (R33, R35).
- **TR17 — Surface documentation.** Update `/sw-deliver` and conductor skill/command descriptions (and
  relevant `docs/guides/*`) so the autonomy/parallelism behavior and the legitimate-halt set are documented
  at the surface a user reads (R36).
- **TR18 — Emitter propagation.** Regenerate `dist/cursor` and `dist/claude-code` via
  `python3 -m sw generate --all`; the freshness gate (`scripts/test/run-emitter-fixtures.sh`) must pass
  (R5).

## Security & Compliance

- **No destructive git / no auto-merge to `main` (R22).** The conductor halts at the terminal merge gate;
  it never merges to `main` or force-pushes, even under full autonomy.
- **Push chokepoint (R23).** Every push routes through `scripts/git-push.sh`; the secret-scan chokepoint
  delivered by PRD 007 remains the local first line of defense — the conductor adds no raw `git push`.
- **Single-flight merge under concurrency (R21).** Parallel phase completion cannot bypass the serialized
  merge queue lock/journal; concurrency never produces a double-merge or a half-applied merge.
- **Background-process hygiene (R9).** Self-wake watchers and heartbeats are uniquely named per run and torn
  down on terminal halt, so an autonomous run leaves no orphaned shells holding tokens or file handles.
- **Memory guardrails unchanged.** The conductor introduces no new memory writes; existing redaction
  chokepoint and human-gated rule-class promotion remain in force.

## Testing Strategy

Fixtures extend the existing harness invoked by `workflow.config.json` `verify.test` (notably
`run-deliver-fixtures.sh`, `run-deliver-loop-fixtures.sh`, `run-state-fixtures.sh`,
`run-merge-queue-fixtures.sh`, `run-orchestrator-fixtures.sh`, `run-emitter-fixtures.sh`).

| Fixture | Asserts | R-IDs |
|---------|---------|-------|
| `conductor-contract-single-source` | one referenced conductor skill/rule; orchestrators reference, not duplicate | R1, R3 |
| `conductor-drives-without-human-step` | mechanical + agent steps proceed with no human message between them | R2 |
| `conductor-fresh-agent-resume` | a fresh agent resumes from durable state to the next legitimate halt | R4 |
| `conductor-emitter-freshness` | conductor contract emitted to `dist/cursor` + `dist/claude-code`; gate fresh | R5 |
| `deliver-loop-self-continue-in-turn` | agent action → driver re-invoked in-turn; no "continue" prompt | R6, R7 |
| `conductor-self-wake-ci-wait` | time-gated CI wait arms `notify_on_output` and self-resumes | R8 |
| `conductor-watcher-teardown` | watchers/heartbeats uniquely named per run; torn down; no orphans | R9 |
| `conductor-legitimate-halts-only` | halts only on main-merge / budget-exhausted / ambiguous-conflict / configured checkpoint | R10 |
| `conductor-no-routine-halt` | no halt for per-phase progression, status collect, wave advance, bookkeeping | R11 |
| `conductor-consolidated-halt-report` | every halt emits one actionable report with exact resume command | R12 |
| `conductor-default-no-reprompt` | default config delivers end-to-end with zero re-prompts | R13 |
| `conductor-parallel-wave-dispatch` | ready phases run concurrently as background sub-agents, bounded by ceiling | R14, R16 |
| `conductor-greedy-batch-ceiling` | over-ceiling waves dispatch in greedy batches; running phase never unwound | R15 |
| `conductor-intra-phase-gated` | intra-phase dispatch only when subagent heuristics trip; decision logged | R17 |
| `conductor-ceiling-accounting` | intra-phase dispatch does not consume ceiling slots | R18 |
| `conductor-status-from-durable-only` | outcomes read from `status.json`, never ephemeral logs | R19 |
| `conductor-contention-serialized` | contended phases (migration/INDEX/CHANGELOG) never run concurrently | R20 |
| `conductor-single-flight-merge` | concurrent completion serializes through the merge queue; no double-merge | R21 |
| `conductor-green-gate-no-main-merge` | merge only when green + review-satisfied; never merges `main` | R22 |
| `conductor-push-chokepoint` | all pushes route through `git-push.sh`; no raw `git push` | R23 |
| `conductor-blast-radius` | blocked phase blocks only transitive dependents; green siblings continue | R24 |
| `spec-seed-idempotent-state` | `specSeed` recorded on idempotent skip; no driver loop | R25 |
| `merge-postverify-no-silent-revert` | post-verify failure routes to stabilize + marks blocked; explicit revert | R26 |
| `wave-dispatch-arg-hygiene` | `status collect`, `merge run-next`, `report terminal` work end-to-end via the shell entrypoint | R27 |
| `driver-error-structured-json` | any sub-step failure (incl. keyword-collision path) emits `{verdict:"fail"}` JSON; no TypeError | R28 |
| `phase-status-vocabulary-guard` | guard rejects an out-of-vocabulary status write; merge still sets `green-merged` | R29 |
| `stale-state-refuses-start` | mismatched run identity aborts or resets, not inherits | R30 |
| `provision-detached-head-safe` | clean primary-on-branch auto-handled; dirty primary still fails closed | R31 |
| `reliability-regressions-wired` | R25–R31 fixtures present in the gate (failing-before / passing-after) | R32 |
| `orchestrator-adoption-audit-present` | audit of the four orchestrators committed and complete | R33 |
| `deliver-pilot-validated` | `/sw-deliver` validated against R6–R20 end-to-end | R34 |
| `adoption-requirements-enumerated` | remaining-orchestrator adoption reqs enumerated, reference shared contract | R35 |
| `surface-docs-updated` | autonomy/parallelism + halt set documented at user-read surfaces | R36 |
| `conductor-phase-liveness-timeout` | a phase sub-agent that never writes `status.json` → blocked + clean halt, no hang | R37 |
| `conductor-no-progress-circuit-breaker` | identical `nextAction` + unchanged state N× → clean halt; loop bounded | R38 |
| `conductor-contention-mechanical` | contention derived from plan/declared paths; ambiguous → fail-safe sequential | R39 |
| `conductor-ci-wait-exhausted-halt` | self-wake max-wait → clean halt; wake re-derives from durable state | R40 |
| `conductor-merge-serialized-atomic` | simultaneous completion → exactly one merge; atomic lock; sub-agents never merge | R41 |
| `conductor-run-budget-halt` | run-level ceiling exceeded → clean consolidated halt | R42 |
| `conductor-resume-not-false-aborted` | relocated/relative-path resume of the same run does not false-abort | R43 |
| `conductor-parallel-completion-wake` | bounded poll / self-wake on parallel-wave completion, then autonomous resume | R44 |
| `conductor-no-nested-dispatch-under-parallel` | backgrounded phase degrades intra-phase dispatch to inline | R45 |
| `conductor-self-wake-cloud-fallback` | no auto-resume env → bounded in-turn poll then clean halt | R46 |

## Rollout Plan

- **Single feature branch** `feat/autonomous-orchestration-conductor`, delivered in dependency-ordered
  phases: (1) reliability hardening of the primitives (R25–R32) — including the widened `wave.sh` dispatch
  fix (R27) and structured error paths (R28) — the conductor cannot reach a merge until these are green;
  (2) per-orchestrator audit + enumerated adoption requirements (R33, R35) front-loaded so the contract is
  shaped against all four consumers, not over-fit to `/sw-deliver`; (3) conductor contract artifact + config
  knobs `deliver.autonomy` / run-level budget (R1–R5, R13, R42); (4) in-turn self-continuation with the
  loop hard-stop/circuit breaker + self-wake incl. env fallback and parallel-completion wait
  (R6–R9, R38, R40, R44, R46); (5) legitimate-halt set + consolidated reports + phase liveness watchdog
  (R10–R12, R37); (6) conductor-level parallel dispatch + intra-phase gating/degrade + mechanical contention
  serialization, with safety-invariant concurrency fixtures built alongside (R14–R24, R39, R41, R45);
  (7) `/sw-deliver` pilot validation + surface docs + emitter propagation as the final core-mutating step
  (R5, R34, R36). Phase boundaries track build dependencies; fixtures land with the behavior they cover and
  the emitter regen rides the last phase that mutates `core/`.
- **Backward compatible.** New config key `deliver.autonomy` defaults to `autonomous`; absent key →
  default. Existing supervised behavior is reachable via `deliver.autonomy: supervised` and the existing
  `doc.afterTasks` / `deliver.phaseAckCadence` checkpoints.
- **Bootstrap caution.** Because this PRD repairs and automates the very `/sw-deliver` machinery, the first
  delivery of 009 SHOULD be supervised (`--after-tasks stop` or `deliver.autonomy: supervised`) until the
  reliability fixtures (phase 1) and the conductor contract land green.
- **Emitter.** Regenerate `dist/` after every `core/` change; the freshness gate enforces parity.

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-1 | A conductor skill owns the autonomous loop; `wave_*.py` scripts remain deterministic primitives | The agent work must happen in the agent runtime, not a subprocess; keep the resumable state core that already works (brainstorm D1). |
| DL-2 | One shared conductor contract; `/sw-deliver` is the pilot | The "must re-prompt" gap exists across every orchestrator; a one-off deliver fix would not compound (brainstorm D2). |
| DL-3 | Adaptive, heuristic-gated parallelism with all dispatch at the conductor level | Conductor-level fan-out is a reliable platform contract; nested dispatch is not (per the deliver skill's prior sub-agent-dispatch spike). No capability-detection layer needed (brainstorm D3). |
| DL-4 | Minimal legitimate halts; everything else automatic | Per-step pausing is negative value; halt only for main-merge, exhausted budget, ambiguous/destructive actions, and configured checkpoints (brainstorm D4). |
| DL-5 | In-turn loop plus self-wake for time-gated waits | Stay in-turn for mechanical/agent steps; arm a sentinel only for genuine external waits (CI) rather than blocking the turn or asking the user (brainstorm D5). |
| DL-6 | Reliability hardening (R25–R31) is in-scope and traceable to the PRD 008 run | The conductor can only be hands-off if the primitives it drives are dependable; each defect carries a regression fixture (brainstorm D6, R32). |
| DL-7 | Resolves OQ1 — expose a single `deliver.autonomy: supervised\|autonomous` knob, default `autonomous` | Default-autonomous is the product thesis (the plugin's value is automation), made safe by the bounded legitimate-halt set (R10), per-phase liveness/remediation budgets (R37), and a run-level ceiling (R42) — not by re-prompting. `supervised` and `doc.afterTasks`/`phaseAckCadence` remain available for users who want graduated trust; the first delivery of 009 itself is supervised (Rollout bootstrap caution). |
| DL-8 | Resolves OQ2 — self-wake reuses `checks.watch.pollSeconds`/`maxWaitMinutes` | Reuse the existing CI-watch cadence rather than adding a new backoff knob; fixed interval is sufficient for the pilot. |
| DL-9 | Resolves OQ3 — first iteration keeps intra-phase dispatch to the existing `sw-subagent-dispatch.mdc`-gated task/review behavior | Per-task-set implementation sub-agents add risk without proven need; defer until the wave-level pilot proves the contract (R17). |
| DL-10 | Resolves OQ4 — recommended convergence order after the pilot: `/sw-ship` → `/sw-debug` → `/sw-doc` → `/sw-feedback` | `/sw-ship` is the highest-frequency multi-phase surface and `/sw-debug` the next; ordering is recorded, not built here (R35). |
| DL-11 | Phase liveness watchdog + bounded conductor loop are mandatory, not optional | Under a chaotic runtime a background sub-agent can die silently and an in-turn loop can churn; without a per-phase timeout (R37) and a documented loop hard-stop/circuit breaker (R38) the "never in-flux / no runaway" promise fails on the crash path. |
| DL-12 | Contention detection is mechanical (plan-time edge injection from declared paths), fail-safe to sequential | Prose-based contention classification risks concurrent corruption of `INDEX.md`/`CHANGELOG.md`; ambiguity must serialize, not parallelize (R39). |
| DL-13 | Merge-queue invocation is conductor-serialized with an atomic lock | 009 is the change that introduces concurrency; single-flight must be a stated property here (atomic acquire, sub-agents never merge), not assumed from PRD 007 (R41). |
| DL-14 | Under parallelism, intra-phase dispatch degrades to inline (no nesting) | A backgrounded phase spawning its own sub-agents is exactly the nested dispatch R16 forbids; the degrade rule keeps R16 and R17 consistent (R45). |
| DL-15 | Self-wake has a defined environment fallback and a max-wait clean halt | Output-notification auto-resume is unavailable in cloud/headless agents; the zero-re-prompt promise needs a bounded-poll fallback and an "external wait exhausted" halt to be well-defined everywhere (R40, R46). |
| DL-16 | The audit of the four orchestrators is pulled early (before/with contract authoring) | Authoring a "single shared contract" validated against one consumer risks over-fitting to `/sw-deliver`; the audit front-loads the generalization check (R33, R35). |

## Open Questions

None. All four brainstorm open questions (OQ1–OQ4) are resolved in the Decision Log (DL-7 through DL-10).
